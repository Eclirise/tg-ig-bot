from __future__ import annotations

from datetime import timedelta
import logging
import random

from aiogram import Bot

from app.config import AppConfig
from app.db import Database
from app.downloader.router import DownloaderRouter
from app.models import (
    Subscription,
    SubscriptionStatus,
    SubscriptionType,
    compute_next_check_at,
    to_iso,
    utcnow,
)
from app.services.auth_service import AccessService
from app.services.sender_service import SenderService
from app.services.settings_service import SettingsService
from app.services.stats_service import StatsService
from app.utils.error_classifier import is_auth_error, is_rate_limit_error
from app.utils.url_parser import normalize_username


logger = logging.getLogger(__name__)


def subscription_flags_for_mode(mode: str) -> tuple[bool, bool]:
    mapping = {
        "feed": (True, False),
        "story": (False, True),
        "both": (True, True),
    }
    if mode not in mapping:
        raise ValueError("未知订阅模式。")
    return mapping[mode]


def apply_subscription_action(current_feed: bool, current_story: bool, action: str) -> tuple[bool, bool]:
    if action == "only_feed":
        return True, False
    if action == "only_story":
        return False, True
    if action == "both":
        return True, True
    if action == "disable_feed":
        return False, current_story
    if action == "disable_story":
        return current_feed, False
    if action == "unsubscribe":
        return False, False
    raise ValueError("未知修改动作。")


class SubscriptionService:
    def __init__(
        self,
        db: Database,
        settings_service: SettingsService,
        router: DownloaderRouter,
        sender_service: SenderService,
        stats_service: StatsService,
        access_service: AccessService,
        config: AppConfig,
    ) -> None:
        self.db = db
        self.settings_service = settings_service
        self.router = router
        self.sender_service = sender_service
        self.stats_service = stats_service
        self.access_service = access_service
        self.config = config

    def add_subscription(self, chat_id: int, username: str, mode: str) -> Subscription:
        normalized = normalize_username(username)
        ig_feed_enabled, story_enabled = subscription_flags_for_mode(mode)
        status = SubscriptionStatus.ACTIVE if (ig_feed_enabled or story_enabled) else SubscriptionStatus.INACTIVE
        next_check_at = self._initial_next_check_at() if status == SubscriptionStatus.ACTIVE else None
        self.db.upsert_subscription(
            chat_id,
            normalized,
            ig_feed_enabled=ig_feed_enabled,
            story_enabled=story_enabled,
            status=status,
            next_check_at=to_iso(next_check_at),
        )
        return self.db.get_subscription(chat_id, normalized)  # type: ignore[return-value]

    def modify_subscription(self, chat_id: int, username: str, action: str) -> Subscription:
        normalized = normalize_username(username)
        current = self.db.get_subscription(chat_id, normalized)
        if current is None:
            raise ValueError("未找到该订阅。")
        ig_feed_enabled, story_enabled = apply_subscription_action(
            current.ig_feed_enabled,
            current.story_enabled,
            action,
        )
        status = SubscriptionStatus.ACTIVE if (ig_feed_enabled or story_enabled) else SubscriptionStatus.INACTIVE
        next_check_at = self._initial_next_check_at() if status == SubscriptionStatus.ACTIVE else None
        self.db.upsert_subscription(
            chat_id,
            normalized,
            ig_feed_enabled=ig_feed_enabled,
            story_enabled=story_enabled,
            status=status,
            next_check_at=to_iso(next_check_at),
        )
        return self.db.get_subscription(chat_id, normalized)  # type: ignore[return-value]

    def unsubscribe(self, chat_id: int, username: str) -> Subscription:
        return self.modify_subscription(chat_id, username, "unsubscribe")

    def list_subscriptions(self, chat_id: int) -> list[Subscription]:
        return self.db.list_subscriptions(chat_id)

    def get_subscription(self, chat_id: int, username: str) -> Subscription | None:
        return self.db.get_subscription(chat_id, normalize_username(username))

    def reschedule_chat(self, chat_id: int, *, immediate: bool) -> None:
        next_check_at = self._initial_next_check_at() if immediate else compute_next_check_at(
            self.settings_service.get_poll_interval_minutes(chat_id)
        )
        self.db.reschedule_chat_subscriptions(chat_id, to_iso(next_check_at))

    async def poll_due_subscriptions(self, bot: Bot) -> int:
        due_subscriptions = self.db.list_due_subscriptions(to_iso(utcnow()) or "", limit=self.config.poll_due_limit)
        processed = 0
        for subscription in due_subscriptions:
            if not self.access_service.can_deliver_chat(subscription.chat_id):
                self.db.update_subscription_runtime(
                    subscription.chat_id,
                    subscription.username,
                    status=subscription.status,
                    last_checked_at=to_iso(utcnow()),
                    next_check_at=None,
                    last_error="目标群未启用，轮询已暂停。",
                )
                continue
            await self.process_subscription(bot, subscription)
            processed += 1
        return processed

    async def process_subscription(self, bot: Bot, subscription: Subscription) -> None:
        now = utcnow()
        normal_next_check_at = compute_next_check_at(
            self.settings_service.get_poll_interval_minutes(subscription.chat_id),
            now=now,
        )
        status = SubscriptionStatus.ACTIVE
        error_messages: list[str] = []
        if subscription.ig_feed_enabled:
            try:
                await self._process_subscription_type(bot, subscription, SubscriptionType.IG_FEED)
            except Exception as exc:
                logger.exception("处理 IG 动态订阅失败: chat_id=%s username=%s", subscription.chat_id, subscription.username)
                status = SubscriptionStatus.ERROR
                error_messages.append(f"IG动态: {str(exc)[:160]}")
        if subscription.story_enabled:
            try:
                await self._process_subscription_type(bot, subscription, SubscriptionType.STORY)
            except Exception as exc:
                logger.exception("处理 Story 订阅失败: chat_id=%s username=%s", subscription.chat_id, subscription.username)
                status = SubscriptionStatus.ERROR
                error_messages.append(f"Story: {str(exc)[:160]}")
        next_check_at = self._compute_next_check_at_after_run(
            now=now,
            default_next_check_at=normal_next_check_at,
            error_messages=error_messages,
        )
        self.db.update_subscription_runtime(
            subscription.chat_id,
            subscription.username,
            status=status,
            last_checked_at=to_iso(now),
            next_check_at=to_iso(next_check_at),
            last_error=" | ".join(error_messages) if error_messages else None,
        )

    async def _process_subscription_type(
        self,
        bot: Bot,
        subscription: Subscription,
        subscription_type: SubscriptionType,
    ) -> None:
        checkpoint = self.db.get_checkpoint(subscription.chat_id, subscription.username, subscription_type.value)
        refs = await self.router.fetch_updates(
            subscription.username,
            subscription_type,
            checkpoint,
            limit=self.config.poll_batch_size,
        )
        for ref in refs:
            if self.db.was_delivered(subscription.chat_id, ref.dedupe_key, subscription_type.value):
                self.db.set_checkpoint(
                    subscription.chat_id,
                    subscription.username,
                    subscription_type.value,
                    last_media_at=to_iso(ref.created_at),
                    last_media_key=ref.dedupe_key,
                )
                continue
            result = await self.router.download(ref.source_url)
            result.subscription_type = subscription_type
            sent = await self.sender_service.send_download(bot, subscription.chat_id, result)
            if not sent:
                raise RuntimeError("媒体下载成功，但发送失败。")
            self.db.record_delivered(subscription.chat_id, subscription.username, ref.dedupe_key, subscription_type.value)
            self.db.set_checkpoint(
                subscription.chat_id,
                subscription.username,
                subscription_type.value,
                last_media_at=to_iso(ref.created_at),
                last_media_key=ref.dedupe_key,
            )
            self.stats_service.record_delivery(subscription.chat_id, result, count_parse_request=False)

    def _compute_next_check_at_after_run(self, *, now, default_next_check_at, error_messages: list[str]):
        if not error_messages:
            return default_next_check_at
        merged_error = " | ".join(error_messages)
        if is_rate_limit_error(merged_error):
            delay_minutes = random.randint(
                self.config.rate_limit_backoff_min_minutes,
                self.config.rate_limit_backoff_max_minutes,
            )
            return now + timedelta(minutes=delay_minutes, seconds=random.randint(15, 45))
        if is_auth_error(merged_error):
            delay_minutes = max(self.config.rate_limit_backoff_min_minutes, 60)
            return now + timedelta(minutes=delay_minutes, seconds=random.randint(15, 45))
        fallback_minutes = 15
        return now + timedelta(minutes=fallback_minutes, seconds=random.randint(15, 45))

    @staticmethod
    def _initial_next_check_at():
        return utcnow() + timedelta(seconds=15)


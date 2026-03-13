from __future__ import annotations

from dataclasses import dataclass

from app.config import AppConfig
from app.db import Database


@dataclass(slots=True)
class RuntimeSnapshot:
    poll_interval_minutes: int
    cleanup_policy: str
    backend_order: str
    chat_subscription_count: int
    global_subscription_count: int


class SettingsService:
    POLL_INTERVAL_KEY = "poll_interval_minutes"
    ALLOWED_INTERVALS = (5, 10)

    def __init__(self, db: Database, config: AppConfig) -> None:
        self.db = db
        self.config = config

    def get_poll_interval_minutes(self, chat_id: int) -> int:
        value = self.db.get_setting(chat_id, self.POLL_INTERVAL_KEY)
        if not value:
            return self.config.default_poll_interval_minutes
        try:
            interval = int(value)
        except ValueError:
            return self.config.default_poll_interval_minutes
        if interval not in self.ALLOWED_INTERVALS:
            return self.config.default_poll_interval_minutes
        return interval

    def set_poll_interval_minutes(self, chat_id: int, minutes: int) -> int:
        if minutes not in self.ALLOWED_INTERVALS:
            raise ValueError("轮询频率仅支持 5 分钟或 10 分钟。")
        self.db.set_setting(chat_id, self.POLL_INTERVAL_KEY, str(minutes))
        return minutes

    def cleanup_policy_text(self) -> str:
        if self.config.cleanup_after_send:
            return "发送成功后立即删除，失败任务也不保留长期缓存。"
        return "不会在发送后自动清理，这不适合低配机器。"

    def backend_order_text(self) -> str:
        return "Instaloader -> gallery-dl -> yt-dlp(Reel/视频兜底)"

    def get_runtime_snapshot(self, chat_id: int) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            poll_interval_minutes=self.get_poll_interval_minutes(chat_id),
            cleanup_policy=self.cleanup_policy_text(),
            backend_order=self.backend_order_text(),
            chat_subscription_count=self.db.count_active_subscriptions(chat_id=chat_id),
            global_subscription_count=self.db.count_active_subscriptions(),
        )

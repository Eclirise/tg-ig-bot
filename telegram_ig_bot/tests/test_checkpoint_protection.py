from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db import Database
from app.downloader.types import DownloadResult, MediaItem, RemoteMediaRef
from app.models import MediaType, SubscriptionType
from app.services.auth_service import AccessService
from app.services.cleanup_service import CleanupService
from app.services.settings_service import SettingsService
from app.services.stats_service import StatsService
from app.services.subscription_service import SubscriptionService


class FakeRouter:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    async def fetch_updates(self, username: str, subscription_type: SubscriptionType, checkpoint, *, limit: int):
        base = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc)
        return [
            RemoteMediaRef(
                media_id="m1",
                shortcode="m1",
                source_url="https://www.instagram.com/p/m1/",
                username=username,
                created_at=base,
                subscription_type=subscription_type,
            ),
            RemoteMediaRef(
                media_id="m2",
                shortcode="m2",
                source_url="https://www.instagram.com/p/m2/",
                username=username,
                created_at=base + timedelta(minutes=1),
                subscription_type=subscription_type,
            ),
        ]

    async def download(self, url: str) -> DownloadResult:
        media_id = url.rstrip("/").split("/")[-1]
        temp_dir = self.tmp_path / media_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / f"{media_id}.jpg"
        file_path.write_bytes(b"img")
        return DownloadResult(
            media_id=media_id,
            shortcode=media_id,
            username="example",
            caption=None,
            source_url=url,
            created_at=None,
            temp_dir=temp_dir,
            items=[
                MediaItem(
                    media_id=media_id,
                    shortcode=media_id,
                    media_type=MediaType.IMAGE,
                    local_path=file_path,
                    caption=None,
                    source_url=url,
                    username="example",
                    created_at=None,
                )
            ],
        )


class FakeSender:
    def __init__(self) -> None:
        self.calls = 0

    async def send_download(self, bot, chat_id: int, result: DownloadResult, *, reply_to_message_id=None) -> bool:
        self.calls += 1
        return self.calls == 1


@pytest.mark.asyncio()
async def test_checkpoint_not_advanced_when_second_send_fails(config_factory, tmp_path) -> None:
    config = config_factory()
    config.ensure_directories()
    db = Database(config.db_path)
    db.initialize()
    db.ensure_chat(config.admin_tg_user_id, "admin", "private")
    settings_service = SettingsService(db, config)
    stats_service = StatsService(db, config)
    access_service = AccessService(db, config)
    router = FakeRouter(tmp_path)
    sender = FakeSender()
    service = SubscriptionService(
        db,
        settings_service,
        router,
        sender,
        stats_service,
        access_service,
        config,
    )
    subscription = service.add_subscription(config.admin_tg_user_id, "example", "feed")
    await service.process_subscription(object(), subscription)
    checkpoint = db.get_checkpoint(config.admin_tg_user_id, "example", "ig_feed")
    assert checkpoint is not None
    assert checkpoint.last_media_key == "m1"
    assert db.was_delivered(config.admin_tg_user_id, "m1", "ig_feed") is True
    assert db.was_delivered(config.admin_tg_user_id, "m2", "ig_feed") is False

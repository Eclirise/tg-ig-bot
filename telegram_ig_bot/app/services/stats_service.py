from __future__ import annotations

from app.config import AppConfig
from app.db import Database
from app.downloader.types import DownloadResult
from app.models import DailyStatsSummary, SubscriptionType, local_date_key


class StatsService:
    def __init__(self, db: Database, config: AppConfig) -> None:
        self.db = db
        self.config = config

    def record_delivery(self, chat_id: int, result: DownloadResult, *, count_parse_request: bool) -> None:
        date_key = local_date_key(self.config.app_timezone)
        targets = [0]
        if chat_id != 0:
            targets.append(chat_id)
        for target_chat_id in targets:
            if count_parse_request:
                self.db.increment_daily_stat(date_key, target_chat_id, "parse_requests_success", 1)
            if result.subscription_type == SubscriptionType.STORY or "/stories/" in result.source_url:
                self.db.increment_daily_stat(date_key, target_chat_id, "story_bundles_sent", 1)
            else:
                self.db.increment_daily_stat(date_key, target_chat_id, "feed_bundles_sent", 1)
            photos = sum(1 for item in result.items if item.media_type.value == "image")
            videos = sum(1 for item in result.items if item.media_type.value == "video")
            self.db.increment_daily_stat(date_key, target_chat_id, "photos_sent", photos)
            self.db.increment_daily_stat(date_key, target_chat_id, "videos_sent", videos)

    def get_today_summary(self, *, chat_id: int = 0) -> DailyStatsSummary:
        date_key = local_date_key(self.config.app_timezone)
        return self.db.get_daily_stats(date_key, chat_id=chat_id)

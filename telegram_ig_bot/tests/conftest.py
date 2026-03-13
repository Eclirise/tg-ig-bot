from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig


@pytest.fixture()
def config_factory(tmp_path: Path):
    def _make() -> AppConfig:
        return AppConfig(
            project_dir=tmp_path,
            data_dir=tmp_path / "data",
            logs_dir=tmp_path / "logs",
            temp_root=tmp_path / "tmp",
            db_path=tmp_path / "data" / "test.sqlite3",
            telegram_bot_token="token",
            admin_tg_user_id=123456,
            app_timezone="Asia/Shanghai",
            instagram_username=None,
            instagram_session_file=None,
            instagram_cookies_file=None,
            instaloader_binary="instaloader",
            gallery_dl_binary="gallery-dl",
            yt_dlp_binary="yt-dlp",
            log_level="INFO",
            log_max_bytes=262144,
            log_backup_count=2,
            log_to_stdout=False,
            download_timeout_seconds=60,
            max_concurrent_downloads=1,
            scheduler_tick_seconds=60,
            default_poll_interval_minutes=10,
            cleanup_after_send=True,
            cleanup_on_failure=True,
            poll_batch_size=3,
            poll_due_limit=10,
            telegram_alerts_enabled=False,
            telegram_alert_min_interval_seconds=900,
            rate_limit_backoff_min_minutes=30,
            rate_limit_backoff_max_minutes=120,
            ig_rate_limit_cooldown_min_seconds=90,
            ig_rate_limit_cooldown_max_seconds=240,
        )
    return _make

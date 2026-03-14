from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数，当前值为 {value!r}。") from exc


def _env_path(name: str) -> Path | None:
    value = os.getenv(name)
    if not value:
        return None
    return Path(value).expanduser()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppConfig:
    project_dir: Path
    data_dir: Path
    logs_dir: Path
    temp_root: Path
    db_path: Path
    telegram_bot_token: str
    admin_tg_user_id: int
    app_timezone: str
    instagram_username: str | None
    instagram_session_file: Path | None
    instagram_cookies_file: Path | None
    instaloader_binary: str
    gallery_dl_binary: str
    yt_dlp_binary: str
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    log_to_stdout: bool
    download_timeout_seconds: int
    max_concurrent_downloads: int
    scheduler_tick_seconds: int
    default_poll_interval_minutes: int
    cleanup_after_send: bool
    cleanup_on_failure: bool
    poll_batch_size: int
    poll_due_limit: int
    telegram_alerts_enabled: bool
    telegram_alert_min_interval_seconds: int
    rate_limit_backoff_min_minutes: int
    rate_limit_backoff_max_minutes: int
    ig_rate_limit_cooldown_min_seconds: int
    ig_rate_limit_cooldown_max_seconds: int

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        if self.instagram_session_file:
            self.instagram_session_file.parent.mkdir(parents=True, exist_ok=True)
        if self.instagram_cookies_file:
            self.instagram_cookies_file.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    project_dir = Path(__file__).resolve().parents[1]
    env_file = project_dir / ".env"
    if env_file.exists() and not os.access(env_file, os.R_OK):
        raise RuntimeError(f"配置文件不可读：{env_file}")
    load_dotenv(env_file)

    data_dir = _env_path("DATA_DIR") or project_dir / "data"
    logs_dir = _env_path("LOGS_DIR") or project_dir / "logs"
    temp_root = _env_path("TEMP_ROOT") or data_dir / "tmp"
    db_path = _env_path("SQLITE_PATH") or data_dir / "telegram_ig_bot.sqlite3"
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_bot_token:
        raise RuntimeError("缺少 TELEGRAM_BOT_TOKEN 配置。")
    admin_tg_user_id = _env_int("ADMIN_TG_USER_ID", 0)
    if admin_tg_user_id <= 0:
        raise RuntimeError("缺少 ADMIN_TG_USER_ID 配置。")

    default_poll_interval = _env_int("DEFAULT_POLL_INTERVAL_MINUTES", 10)
    if default_poll_interval not in {5, 10}:
        default_poll_interval = 10

    config = AppConfig(
        project_dir=project_dir,
        data_dir=data_dir,
        logs_dir=logs_dir,
        temp_root=temp_root,
        db_path=db_path,
        telegram_bot_token=telegram_bot_token,
        admin_tg_user_id=admin_tg_user_id,
        app_timezone=os.getenv("APP_TIMEZONE", "Asia/Shanghai"),
        instagram_username=os.getenv("INSTAGRAM_USERNAME", "").strip() or None,
        instagram_session_file=_env_path("INSTAGRAM_SESSION_FILE"),
        instagram_cookies_file=_env_path("INSTAGRAM_COOKIES_FILE"),
        instaloader_binary=os.getenv("INSTALOADER_BINARY", "instaloader"),
        gallery_dl_binary=os.getenv("GALLERY_DL_BINARY", "gallery-dl"),
        yt_dlp_binary=os.getenv("YT_DLP_BINARY", "yt-dlp"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_max_bytes=_env_int("LOG_MAX_BYTES", 262144),
        log_backup_count=_env_int("LOG_BACKUP_COUNT", 2),
        log_to_stdout=_env_bool("LOG_TO_STDOUT", True),
        download_timeout_seconds=_env_int("DOWNLOAD_TIMEOUT_SECONDS", 240),
        max_concurrent_downloads=max(1, _env_int("MAX_CONCURRENT_DOWNLOADS", 1)),
        scheduler_tick_seconds=max(30, _env_int("SCHEDULER_TICK_SECONDS", 60)),
        default_poll_interval_minutes=default_poll_interval,
        cleanup_after_send=_env_bool("CLEANUP_AFTER_SEND", True),
        cleanup_on_failure=_env_bool("CLEANUP_ON_FAILURE", True),
        poll_batch_size=max(1, _env_int("POLL_BATCH_SIZE", 3)),
        poll_due_limit=max(1, _env_int("POLL_DUE_LIMIT", 10)),
        telegram_alerts_enabled=_env_bool("TELEGRAM_ALERTS_ENABLED", True),
        telegram_alert_min_interval_seconds=max(60, _env_int("TELEGRAM_ALERT_MIN_INTERVAL_SECONDS", 900)),
        rate_limit_backoff_min_minutes=max(10, _env_int("RATE_LIMIT_BACKOFF_MINUTES", 30)),
        rate_limit_backoff_max_minutes=max(20, _env_int("RATE_LIMIT_BACKOFF_MAX_MINUTES", 120)),
        ig_rate_limit_cooldown_min_seconds=max(30, _env_int("IG_RATE_LIMIT_COOLDOWN_MIN_SECONDS", 90)),
        ig_rate_limit_cooldown_max_seconds=max(60, _env_int("IG_RATE_LIMIT_COOLDOWN_MAX_SECONDS", 240)),
    )
    if config.rate_limit_backoff_max_minutes < config.rate_limit_backoff_min_minutes:
        config.rate_limit_backoff_max_minutes = config.rate_limit_backoff_min_minutes
    if config.ig_rate_limit_cooldown_max_seconds < config.ig_rate_limit_cooldown_min_seconds:
        config.ig_rate_limit_cooldown_max_seconds = config.ig_rate_limit_cooldown_min_seconds
    config.ensure_directories()
    return config

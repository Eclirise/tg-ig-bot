from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot

from app.config import AppConfig
from app.services.alert_service import AlertService


class TelegramAlertHandler(logging.Handler):
    def __init__(self, alert_service: AlertService) -> None:
        super().__init__(level=logging.ERROR)
        self.alert_service = alert_service
        self._ignored_prefixes = (
            "aiogram",
            "apscheduler",
            "app.services.parse_service",
            "app.services.alert_service",
        )

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(self._ignored_prefixes):
            return
        try:
            self.alert_service.schedule_log_alert(record)
        except Exception:
            pass


def setup_logging(config: AppConfig) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.log_level, logging.INFO))
    if root.handlers:
        root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if config.log_to_stdout:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    file_handler = RotatingFileHandler(
        config.logs_dir / "telegram_ig_bot.log",
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def install_telegram_alert_handler(bot: Bot, config: AppConfig) -> AlertService:
    loop = asyncio.get_running_loop()
    alert_service = AlertService(bot, config, loop)
    handler = TelegramAlertHandler(alert_service)
    logging.getLogger().addHandler(handler)
    return alert_service

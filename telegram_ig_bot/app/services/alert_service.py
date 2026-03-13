from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import socket
import traceback

from aiogram import Bot

from app.config import AppConfig


logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, bot: Bot, config: AppConfig, loop: asyncio.AbstractEventLoop) -> None:
        self.bot = bot
        self.config = config
        self.loop = loop
        self.hostname = socket.gethostname()
        self._lock = asyncio.Lock()
        self._last_sent_at: dict[str, datetime] = {}
        self._tasks: set[asyncio.Task[object]] = set()

    def schedule_text_alert(self, title: str, detail: str, *, key: str | None = None, force: bool = False) -> None:
        if not self.config.telegram_alerts_enabled:
            return
        message = self._render_alert(title, detail)
        self.loop.call_soon_threadsafe(self._create_task, self.notify(message, key=key, force=force))

    def schedule_log_alert(self, record: logging.LogRecord) -> None:
        if not self.config.telegram_alerts_enabled:
            return
        message = self._render_log_record(record)
        fingerprint = f"log:{record.name}:{record.levelname}:{record.getMessage()[:180]}"
        self.loop.call_soon_threadsafe(self._create_task, self.notify(message, key=fingerprint, force=False))

    async def notify(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
        if not self.config.telegram_alerts_enabled:
            return False
        async with self._lock:
            if key and not force:
                previous = self._last_sent_at.get(key)
                if previous is not None:
                    elapsed = (datetime.now(timezone.utc) - previous).total_seconds()
                    if elapsed < self.config.telegram_alert_min_interval_seconds:
                        return False
            if key:
                self._last_sent_at[key] = datetime.now(timezone.utc)
        try:
            await self.bot.send_message(self.config.admin_tg_user_id, text[:3900])
            return True
        except Exception as exc:
            logger.warning("发送管理员告警失败: %s", exc)
            return False

    def _create_task(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _render_alert(self, title: str, detail: str) -> str:
        now_text = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return "\n".join(
            [
                f"【{title}】",
                f"主机：{self.hostname}",
                f"时间：{now_text}",
                "",
                detail[:3200],
            ]
        )

    def _render_log_record(self, record: logging.LogRecord) -> str:
        base = f"{record.name} | {record.levelname}\n{record.getMessage()}"
        if record.exc_info:
            formatted_exception = "".join(traceback.format_exception(*record.exc_info))
            base = f"{base}\n\n{formatted_exception[-1600:]}"
        return self._render_alert("Bot 异常日志", base)

from __future__ import annotations

import logging

from aiogram import Bot

from app.downloader.base import DownloadError
from app.downloader.router import DownloaderRouter
from app.services.sender_service import SenderService
from app.services.stats_service import StatsService


logger = logging.getLogger(__name__)


class ParseService:
    def __init__(
        self,
        router: DownloaderRouter,
        sender_service: SenderService,
        stats_service: StatsService,
    ) -> None:
        self.router = router
        self.sender_service = sender_service
        self.stats_service = stats_service

    async def parse_and_send(
        self,
        bot: Bot,
        chat_id: int,
        url: str,
        *,
        progress_message_id: int | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        result = None
        try:
            result = await self.router.download(url)
            success = await self.sender_service.send_download(
                bot,
                chat_id,
                result,
                reply_to_message_id=reply_to_message_id,
            )
            if not success:
                raise DownloadError("媒体已解析，但发送到 Telegram 失败。")
            self.stats_service.record_delivery(chat_id, result, count_parse_request=True)
            await self._set_progress(bot, chat_id, progress_message_id, f"解析完成，已发送。后端：{result.backend_name}")
        except Exception as exc:
            logger.exception("手动解析失败: chat_id=%s url=%s", chat_id, url)
            await self._set_progress(bot, chat_id, progress_message_id, f"解析失败：{self._safe_error_text(exc)}")

    async def _set_progress(
        self,
        bot: Bot,
        chat_id: int,
        progress_message_id: int | None,
        text: str,
    ) -> None:
        if progress_message_id is None:
            await bot.send_message(chat_id, text)
            return
        try:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=progress_message_id)
        except Exception:
            await bot.send_message(chat_id, text)

    @staticmethod
    def _safe_error_text(exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:180]

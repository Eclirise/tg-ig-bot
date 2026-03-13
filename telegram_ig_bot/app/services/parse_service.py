from __future__ import annotations

import logging

from aiogram import Bot

from app.downloader.base import DownloadError
from app.downloader.router import DownloaderRouter
from app.services.sender_service import SenderService
from app.services.stats_service import StatsService
from app.utils.url_parser import parse_supported_url


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
        current_progress_message_id = progress_message_id
        try:
            parsed_url = parse_supported_url(url)
            current_progress_message_id = await self._replace_progress(
                bot,
                chat_id,
                current_progress_message_id,
                f"正在下载{self._platform_label(parsed_url)}内容，请稍候。",
            )
            result = await self.router.download(url)
            current_progress_message_id = await self._replace_progress(
                bot,
                chat_id,
                current_progress_message_id,
                f"下载完成，正在发送{self._describe_result(result)}。",
            )

            async def update_send_progress(sent_units: int, total_units: int) -> None:
                nonlocal current_progress_message_id
                current_progress_message_id = await self._replace_progress(
                    bot,
                    chat_id,
                    current_progress_message_id,
                    self._sending_progress_text(result, sent_units, total_units),
                )

            success = await self.sender_service.send_download(
                bot,
                chat_id,
                result,
                reply_to_message_id=reply_to_message_id,
                progress_callback=update_send_progress,
            )
            if not success:
                raise DownloadError("媒体已解析，但发送到 Telegram 失败。")
            self.stats_service.record_delivery(chat_id, result, count_parse_request=True)
            await self._clear_progress(bot, chat_id, current_progress_message_id)
        except Exception as exc:
            logger.exception("手动解析失败: chat_id=%s url=%s", chat_id, url)
            await self._replace_progress(
                bot,
                chat_id,
                current_progress_message_id,
                f"解析失败：{self._safe_error_text(exc)}",
            )

    async def _replace_progress(
        self,
        bot: Bot,
        chat_id: int,
        progress_message_id: int | None,
        text: str,
    ) -> int | None:
        await self._clear_progress(bot, chat_id, progress_message_id)
        try:
            message = await bot.send_message(chat_id, text)
            return message.message_id
        except Exception:
            return progress_message_id

    async def _clear_progress(
        self,
        bot: Bot,
        chat_id: int,
        progress_message_id: int | None,
    ) -> None:
        if progress_message_id is None:
            return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=progress_message_id)
        except Exception:
            pass

    @staticmethod
    def _describe_result(result) -> str:
        if len(result.items) > 1:
            return "图集"
        item = result.items[0]
        if item.media_type.name == "VIDEO":
            return "视频"
        if item.media_type.name == "IMAGE":
            return "图片"
        return "文件"

    def _sending_progress_text(self, result, sent_units: int, total_units: int) -> str:
        media_text = self._describe_result(result)
        if total_units <= 1:
            return f"正在发送{media_text}。"
        return f"正在发送{media_text}，进度 {sent_units}/{total_units}。"

    @staticmethod
    def _platform_label(parsed_url) -> str:
        if parsed_url.is_youtube:
            return " YouTube "
        return " Instagram "

    @staticmethod
    def _safe_error_text(exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:180]

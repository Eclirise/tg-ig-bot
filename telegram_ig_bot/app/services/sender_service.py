from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo

from app.config import AppConfig
from app.downloader.types import DownloadResult, MediaItem
from app.models import MediaType
from app.services.cleanup_service import CleanupService


logger = logging.getLogger(__name__)


class SenderService:
    def __init__(self, cleanup_service: CleanupService, config: AppConfig) -> None:
        self.cleanup_service = cleanup_service
        self.config = config

    async def send_download(
        self,
        bot: Bot,
        chat_id: int,
        result: DownloadResult,
        *,
        reply_to_message_id: int | None = None,
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> bool:
        sent_ok = False
        try:
            if len(result.items) == 1:
                await self._send_single(
                    bot,
                    chat_id,
                    result.items[0],
                    result.caption,
                    reply_to_message_id=reply_to_message_id,
                )
                if progress_callback is not None:
                    await progress_callback(1, 1)
            else:
                batches = self._chunks(result.items, 10)
                total_batches = len(batches)
                for batch_index, batch in enumerate(batches):
                    caption = result.caption if batch_index == 0 else None
                    media_group = []
                    for item_index, item in enumerate(batch):
                        item_caption = caption if item_index == 0 else None
                        if item.media_type == MediaType.VIDEO:
                            media_group.append(
                                InputMediaVideo(
                                    media=FSInputFile(str(item.local_path)),
                                    caption=self._trim_caption(item_caption),
                                )
                            )
                        else:
                            media_group.append(
                                InputMediaPhoto(
                                    media=FSInputFile(str(item.local_path)),
                                    caption=self._trim_caption(item_caption),
                                )
                            )
                    await bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group,
                        reply_to_message_id=reply_to_message_id,
                        allow_sending_without_reply=True,
                    )
                    if progress_callback is not None:
                        await progress_callback(batch_index + 1, total_batches)
            sent_ok = True
            return True
        except Exception:
            logger.exception("Telegram ????: chat_id=%s source=%s", chat_id, result.source_url)
            return False
        finally:
            if (sent_ok and self.config.cleanup_after_send) or ((not sent_ok) and self.config.cleanup_on_failure):
                await self.cleanup_service.cleanup_download(result)

    async def _send_single(
        self,
        bot: Bot,
        chat_id: int,
        item: MediaItem,
        caption: str | None,
        *,
        reply_to_message_id: int | None,
    ) -> None:
        if item.media_type == MediaType.VIDEO:
            await bot.send_video(
                chat_id=chat_id,
                video=FSInputFile(str(item.local_path)),
                caption=self._trim_caption(caption),
                supports_streaming=True,
                reply_to_message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            )
            return
        if item.media_type == MediaType.IMAGE:
            await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(str(item.local_path)),
                caption=self._trim_caption(caption),
                reply_to_message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            )
            return
        await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(str(item.local_path)),
            caption=self._trim_caption(caption),
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=True,
        )

    @staticmethod
    def _trim_caption(caption: str | None) -> str | None:
        if not caption:
            return None
        return caption[:1024]

    @staticmethod
    def _chunks(items: list[MediaItem], size: int) -> list[list[MediaItem]]:
        return [items[index:index + size] for index in range(0, len(items), size)]

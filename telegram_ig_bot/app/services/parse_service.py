from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from aiogram import Bot

from app.downloader.base import DownloadError
from app.downloader.router import DownloaderRouter
from app.services.sender_service import SenderService
from app.services.stats_service import StatsService
from app.utils.error_classifier import is_auth_error, is_rate_limit_error
from app.utils.url_parser import parse_supported_url


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ParseQueueSnapshot:
    active_jobs: int
    waiting_jobs: int


class ParseService:
    def __init__(
        self,
        router: DownloaderRouter,
        sender_service: SenderService,
        stats_service: StatsService,
        *,
        max_concurrent_jobs: int,
    ) -> None:
        self.router = router
        self.sender_service = sender_service
        self.stats_service = stats_service
        self.max_concurrent_jobs = max(1, max_concurrent_jobs)
        self._semaphore = asyncio.Semaphore(self.max_concurrent_jobs)
        self._queue_lock = asyncio.Lock()
        self._active_jobs = 0
        self._waiting_jobs = 0

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
        queue_registered = False
        try:
            parsed_url = parse_supported_url(url)
            queue_ahead = await self._register_waiting_job()
            queue_registered = True
            if queue_ahead > 0:
                snapshot = await self.get_queue_snapshot()
                current_progress_message_id = await self._replace_progress(
                    bot,
                    chat_id,
                    current_progress_message_id,
                    self._queued_progress_text(queue_ahead, snapshot),
                )

            await self._semaphore.acquire()
            snapshot = await self._mark_job_started()
            current_progress_message_id = await self._replace_progress(
                bot,
                chat_id,
                current_progress_message_id,
                self._starting_progress_text(parsed_url, snapshot),
            )
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
        finally:
            if queue_registered:
                await self._finish_job()

    async def get_queue_snapshot(self) -> ParseQueueSnapshot:
        async with self._queue_lock:
            return ParseQueueSnapshot(
                active_jobs=self._active_jobs,
                waiting_jobs=self._waiting_jobs,
            )

    async def _register_waiting_job(self) -> int:
        async with self._queue_lock:
            self._waiting_jobs += 1
            return max(0, self._active_jobs + self._waiting_jobs - self.max_concurrent_jobs)

    async def _mark_job_started(self) -> ParseQueueSnapshot:
        async with self._queue_lock:
            self._waiting_jobs = max(0, self._waiting_jobs - 1)
            self._active_jobs += 1
            return ParseQueueSnapshot(
                active_jobs=self._active_jobs,
                waiting_jobs=self._waiting_jobs,
            )

    async def _finish_job(self) -> None:
        released = False
        async with self._queue_lock:
            if self._active_jobs > 0:
                self._active_jobs -= 1
                released = True
            elif self._waiting_jobs > 0:
                self._waiting_jobs -= 1
        if released:
            self._semaphore.release()

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

    def _queued_progress_text(self, queue_ahead: int, snapshot: ParseQueueSnapshot) -> str:
        return (
            f"任务已进入队列，前面还有 {queue_ahead} 个任务。\n"
            f"当前正在解析 {snapshot.active_jobs} 个任务，等待中 {snapshot.waiting_jobs} 个。"
        )

    def _starting_progress_text(self, parsed_url, snapshot: ParseQueueSnapshot) -> str:
        return (
            f"开始解析{self._platform_label(parsed_url)}内容。\n"
            f"当前正在解析 {snapshot.active_jobs} 个任务，等待中 {snapshot.waiting_jobs} 个。"
        )

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
        if isinstance(exc, TimeoutError) or "超时" in text:
            return "下载超时，请稍后重试。"
        if is_rate_limit_error(text):
            return "Instagram 当前触发限流，请稍后再试。"
        if is_auth_error(text):
            return "Instagram 登录态可能失效，请联系管理员刷新 session / cookies。"
        return text[:180]

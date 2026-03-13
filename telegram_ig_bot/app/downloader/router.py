from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path

from app.downloader.base import DownloadError, DownloaderBackend, ListingError
from app.downloader.types import DownloadResult, RemoteMediaRef
from app.models import SubscriptionCheckpoint, SubscriptionType
from app.utils.error_classifier import is_rate_limit_error
from app.utils.retry import async_retry
from app.utils.tempfiles import cleanup_path, create_temp_dir
from app.utils.url_parser import InstagramTargetType, MediaPlatform, parse_supported_url


logger = logging.getLogger(__name__)


class DownloaderRouter:
    def __init__(
        self,
        backends: list[DownloaderBackend],
        *,
        temp_root: Path,
        max_concurrent_downloads: int = 2,
        rate_limit_cooldown_min_seconds: int = 90,
        rate_limit_cooldown_max_seconds: int = 240,
    ) -> None:
        self.backends = backends
        self.temp_root = temp_root
        self._semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.rate_limit_cooldown_min_seconds = max(30, rate_limit_cooldown_min_seconds)
        self.rate_limit_cooldown_max_seconds = max(
            self.rate_limit_cooldown_min_seconds,
            rate_limit_cooldown_max_seconds,
        )
        self._cooldown_until_monotonic = 0.0

    def _iter_download_backends(self, target_type: InstagramTargetType) -> list[DownloaderBackend]:
        ordered: list[DownloaderBackend] = []
        for backend in self.backends:
            if backend.name == "yt-dlp" and target_type == InstagramTargetType.STORY:
                continue
            ordered.append(backend)
        return ordered

    def _iter_download_backends_for_platform(
        self,
        *,
        platform: MediaPlatform,
        target_type: InstagramTargetType | None,
    ) -> list[DownloaderBackend]:
        if platform == MediaPlatform.YOUTUBE:
            return [backend for backend in self.backends if backend.name == "yt-dlp"]
        if target_type is None:
            raise DownloadError("无法识别 Instagram 链接类型。")
        return self._iter_download_backends(target_type)

    async def download(self, url: str) -> DownloadResult:
        parsed_url = parse_supported_url(url)
        last_error: BaseException | None = None
        async with self._semaphore:
            await self.wait_for_rate_limit_cooldown()
            for backend in self._iter_download_backends_for_platform(
                platform=parsed_url.platform,
                target_type=parsed_url.target_type,
            ):
                temp_dir = create_temp_dir(self.temp_root, prefix=f"{backend.name}-")
                try:
                    result = await async_retry(
                        lambda: backend.download_url(url, parsed_url, temp_dir),
                        attempts=2,
                        base_delay=1.0,
                        retry_exceptions=(DownloadError, OSError, RuntimeError),
                    )
                    result.backend_name = backend.name
                    result.temp_dir = temp_dir
                    logger.info(
                        "下载成功: backend=%s platform=%s url=%s",
                        backend.name,
                        parsed_url.platform.value,
                        parsed_url.normalized_url,
                    )
                    return result
                except Exception as exc:
                    last_error = exc
                    cleanup_path(temp_dir)
                    if self.register_rate_limit_cooldown(str(exc), operation="download", backend_name=backend.name):
                        break
                    logger.warning("下载后端失败，准备切换: backend=%s error=%s", backend.name, exc)
        error_text = str(last_error) if last_error else "未知错误"
        raise DownloadError(f"所有下载后端均失败：{error_text}")

    async def fetch_updates(
        self,
        username: str,
        subscription_type: SubscriptionType,
        checkpoint: SubscriptionCheckpoint | None,
        *,
        limit: int,
    ) -> list[RemoteMediaRef]:
        last_error: BaseException | None = None
        await self.wait_for_rate_limit_cooldown()
        for backend in self.backends:
            if not backend.supports_listing:
                continue
            try:
                refs = await async_retry(
                    lambda: backend.fetch_updates(username, subscription_type, checkpoint, limit=limit),
                    attempts=2,
                    base_delay=1.0,
                    retry_exceptions=(ListingError, RuntimeError, OSError),
                )
                logger.info(
                    "拉取更新成功: backend=%s username=%s type=%s count=%s",
                    backend.name,
                    username,
                    subscription_type.value,
                    len(refs),
                )
                return refs
            except Exception as exc:
                last_error = exc
                if self.register_rate_limit_cooldown(
                    str(exc),
                    operation="listing",
                    backend_name=backend.name,
                ):
                    break
                logger.warning(
                    "拉取更新失败，准备切换: backend=%s username=%s type=%s error=%s",
                    backend.name,
                    username,
                    subscription_type.value,
                    exc,
                )
        error_text = str(last_error) if last_error else "未知错误"
        raise ListingError(f"所有更新拉取后端均失败：{error_text}")

    async def wait_for_rate_limit_cooldown(self) -> None:
        remaining = self.remaining_rate_limit_cooldown_seconds()
        if remaining <= 0:
            return
        logger.warning("当前处于限流冷却，%.1f 秒后再请求 Instagram", remaining)
        await asyncio.sleep(remaining)

    def remaining_rate_limit_cooldown_seconds(self) -> float:
        return max(0.0, self._cooldown_until_monotonic - time.monotonic())

    def register_rate_limit_cooldown(self, error_text: str, *, operation: str, backend_name: str) -> bool:
        if not is_rate_limit_error(error_text):
            return False
        delay_seconds = random.randint(
            self.rate_limit_cooldown_min_seconds,
            self.rate_limit_cooldown_max_seconds,
        )
        self._cooldown_until_monotonic = max(
            self._cooldown_until_monotonic,
            time.monotonic() + delay_seconds,
        )
        logger.warning(
            "触发 Instagram 限流冷却: operation=%s backend=%s cooldown=%ss error=%s",
            operation,
            backend_name,
            delay_seconds,
            error_text[:200],
        )
        return True

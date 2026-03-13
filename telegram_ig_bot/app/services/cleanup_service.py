from __future__ import annotations

import asyncio
from pathlib import Path

from app.downloader.types import DownloadResult
from app.utils.tempfiles import cleanup_path


class CleanupService:
    async def cleanup_download(self, result: DownloadResult | None) -> None:
        if result is None:
            return
        await self.cleanup_path(result.temp_dir)

    async def cleanup_path(self, path: Path | None) -> None:
        await asyncio.to_thread(cleanup_path, path)

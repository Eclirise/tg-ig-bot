from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import AppConfig
from app.downloader.base import DownloadError, DownloaderBackend
from app.downloader.types import DownloadResult, MediaItem
from app.models import MediaType
from app.utils.url_parser import ParsedMediaUrl


class YtDlpBackend(DownloaderBackend):
    name = "yt-dlp"
    supports_listing = False

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def download_url(
        self,
        url: str,
        parsed_url: ParsedMediaUrl,
        temp_dir: Path,
    ) -> DownloadResult:
        args = [
            self.config.yt_dlp_binary,
            "--no-playlist",
            "--no-warnings",
            "--restrict-filenames",
            "-P",
            str(temp_dir),
            "-o",
            "%(id)s.%(ext)s",
        ]
        if self.config.instagram_cookies_file and self.config.instagram_cookies_file.exists():
            args.extend(["--cookies", str(self.config.instagram_cookies_file)])
        args.append(url)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="ignore").strip() or stdout.decode("utf-8", errors="ignore").strip()
            raise DownloadError(detail or f"yt-dlp 退出码 {process.returncode}")
        files = self._collect_media_files(temp_dir)
        if not files:
            raise DownloadError("yt-dlp 未产生任何媒体文件。")
        items = [
            MediaItem(
                media_id=file.stem,
                shortcode=parsed_url.shortcode,
                media_type=self._media_type_for_path(file),
                local_path=file,
                caption=None,
                source_url=parsed_url.normalized_url,
                username=parsed_url.username,
                created_at=None,
            )
            for file in files
        ]
        return DownloadResult(
            media_id=parsed_url.shortcode or parsed_url.video_id or items[0].media_id,
            shortcode=parsed_url.shortcode,
            username=parsed_url.username,
            caption=None,
            source_url=parsed_url.normalized_url,
            created_at=None,
            items=items,
        )

    @staticmethod
    def _collect_media_files(temp_dir: Path) -> list[Path]:
        ignored_suffixes = {".json", ".part", ".ytdl", ".txt"}
        files = [
            path
            for path in temp_dir.rglob("*")
            if path.is_file() and path.suffix.lower() not in ignored_suffixes
        ]
        files.sort()
        return files

    @staticmethod
    def _media_type_for_path(path: Path) -> MediaType:
        if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
            return MediaType.VIDEO
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            return MediaType.IMAGE
        return MediaType.UNKNOWN

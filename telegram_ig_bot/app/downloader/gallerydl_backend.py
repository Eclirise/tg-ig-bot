from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from app.config import AppConfig
from app.downloader.base import DownloadError, DownloaderBackend, ListingError
from app.downloader.types import DownloadResult, MediaItem, RemoteMediaRef
from app.models import MediaType, SubscriptionCheckpoint, SubscriptionType
from app.utils.url_parser import ParsedInstagramUrl, build_post_url, build_story_url


class GalleryDLBackend(DownloaderBackend):
    name = "gallery-dl"
    supports_listing = True

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def download_url(
        self,
        url: str,
        parsed_url: ParsedInstagramUrl,
        temp_dir: Path,
    ) -> DownloadResult:
        args = [
            self.config.gallery_dl_binary,
            "--ignore-config",
            "--dest",
            str(temp_dir),
            "--write-info-json",
            "--no-mtime",
        ]
        if self.config.instagram_cookies_file and self.config.instagram_cookies_file.exists():
            args.extend(["--cookies", str(self.config.instagram_cookies_file)])
        args.append(url)
        stdout, stderr = await self._run_command(args)
        files = self._collect_media_files(temp_dir)
        if not files:
            detail = stderr.strip() or stdout.strip() or "gallery-dl 未产生任何媒体文件。"
            raise DownloadError(detail)
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
            media_id=parsed_url.shortcode or items[0].media_id,
            shortcode=parsed_url.shortcode,
            username=parsed_url.username,
            caption=None,
            source_url=parsed_url.normalized_url,
            created_at=None,
            items=items,
        )

    async def fetch_updates(
        self,
        username: str,
        subscription_type: SubscriptionType,
        checkpoint: SubscriptionCheckpoint | None,
        *,
        limit: int,
    ) -> list[RemoteMediaRef]:
        target_url = (
            f"https://www.instagram.com/{username}/"
            if subscription_type == SubscriptionType.IG_FEED
            else f"https://www.instagram.com/stories/{username}/"
        )
        args = [
            self.config.gallery_dl_binary,
            "--ignore-config",
            "--range",
            f"1-{limit}",
            "--dump-json",
        ]
        if self.config.instagram_cookies_file and self.config.instagram_cookies_file.exists():
            args.extend(["--cookies", str(self.config.instagram_cookies_file)])
        args.append(target_url)
        try:
            stdout, stderr = await self._run_command(args)
        except DownloadError as exc:
            raise ListingError(str(exc)) from exc
        refs: list[RemoteMediaRef] = []
        if not stdout.strip():
            if stderr.strip():
                raise ListingError(stderr.strip())
            return []
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            media_id = str(payload.get("id") or payload.get("media_id") or "")
            shortcode = payload.get("shortcode") or payload.get("post_shortcode")
            if not media_id and not shortcode:
                continue
            source_url = self._extract_source_url(payload, username, subscription_type, shortcode, media_id)
            if not source_url:
                continue
            created_at = self._parse_created_at(payload)
            dedupe_key = shortcode or media_id
            if not self._is_newer_than_checkpoint(created_at, dedupe_key, checkpoint):
                continue
            refs.append(
                RemoteMediaRef(
                    media_id=media_id or str(shortcode),
                    shortcode=shortcode,
                    source_url=source_url,
                    username=username,
                    created_at=created_at,
                    subscription_type=subscription_type,
                )
            )
        refs.sort(key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.dedupe_key))
        return refs

    async def _run_command(self, args: list[str]) -> tuple[str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        out_text = stdout.decode("utf-8", errors="ignore")
        err_text = stderr.decode("utf-8", errors="ignore")
        if process.returncode != 0:
            raise DownloadError(err_text.strip() or out_text.strip() or f"gallery-dl 退出码 {process.returncode}")
        return out_text, err_text

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

    @staticmethod
    def _extract_source_url(
        payload: dict[str, object],
        username: str,
        subscription_type: SubscriptionType,
        shortcode: str | None,
        media_id: str,
    ) -> str | None:
        for key in ("post_url", "page_url", "webpage_url", "url"):
            value = payload.get(key)
            if isinstance(value, str) and "instagram.com" in value:
                return value
        if subscription_type == SubscriptionType.STORY and media_id:
            return build_story_url(username, media_id)
        if shortcode:
            return build_post_url(shortcode)
        return None

    @staticmethod
    def _parse_created_at(payload: dict[str, object]) -> datetime | None:
        for key in ("date", "taken_at", "timestamp"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
        return None

    @staticmethod
    def _is_newer_than_checkpoint(
        created_at: datetime | None,
        dedupe_key: str,
        checkpoint: SubscriptionCheckpoint | None,
    ) -> bool:
        if checkpoint is None:
            return True
        if checkpoint.last_media_at and created_at:
            if created_at > checkpoint.last_media_at:
                return True
            if created_at < checkpoint.last_media_at:
                return False
        if checkpoint.last_media_key and dedupe_key == checkpoint.last_media_key:
            return False
        return True

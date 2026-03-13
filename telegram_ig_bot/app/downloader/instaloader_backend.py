from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

import requests

from app.config import AppConfig
from app.downloader.base import DownloadError, DownloaderBackend, ListingError
from app.downloader.types import DownloadResult, MediaItem, RemoteMediaRef
from app.models import MediaType, SubscriptionCheckpoint, SubscriptionType, normalize_datetime
from app.utils.url_parser import InstagramTargetType, ParsedInstagramUrl, build_post_url, build_story_url


logger = logging.getLogger(__name__)


class InstaloaderBackend(DownloaderBackend):
    name = "instaloader"
    supports_listing = True

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def download_url(
        self,
        url: str,
        parsed_url: ParsedInstagramUrl,
        temp_dir: Path,
    ) -> DownloadResult:
        return await asyncio.to_thread(self._download_url_sync, url, parsed_url, temp_dir)

    async def fetch_updates(
        self,
        username: str,
        subscription_type: SubscriptionType,
        checkpoint: SubscriptionCheckpoint | None,
        *,
        limit: int,
    ) -> list[RemoteMediaRef]:
        return await asyncio.to_thread(
            self._fetch_updates_sync,
            username,
            subscription_type,
            checkpoint,
            limit,
        )

    def _download_url_sync(self, url: str, parsed_url: ParsedInstagramUrl, temp_dir: Path) -> DownloadResult:
        try:
            loader = self._build_loader()
            if parsed_url.target_type == InstagramTargetType.STORY:
                return self._download_story(loader, parsed_url, temp_dir)
            return self._download_post_like(loader, parsed_url, temp_dir)
        except Exception as exc:
            raise DownloadError(str(exc)) from exc

    def _fetch_updates_sync(
        self,
        username: str,
        subscription_type: SubscriptionType,
        checkpoint: SubscriptionCheckpoint | None,
        limit: int,
    ) -> list[RemoteMediaRef]:
        try:
            loader = self._build_loader()
            if subscription_type == SubscriptionType.IG_FEED:
                return self._fetch_feed_updates(loader, username, checkpoint, limit)
            return self._fetch_story_updates(loader, username, checkpoint, limit)
        except Exception as exc:
            raise ListingError(str(exc)) from exc

    def _build_loader(self):
        import instaloader

        loader = instaloader.Instaloader(
            sleep=False,
            quiet=True,
            download_comments=False,
            save_metadata=False,
            download_geotags=False,
            post_metadata_txt_pattern="",
            storyitem_metadata_txt_pattern="",
            dirname_pattern="{target}",
            filename_pattern="{shortcode}",
        )
        if self.config.instagram_username and self.config.instagram_session_file and self.config.instagram_session_file.exists():
            loader.load_session_from_file(
                self.config.instagram_username,
                filename=str(self.config.instagram_session_file),
            )
        return loader

    def _download_post_like(self, loader: Any, parsed_url: ParsedInstagramUrl, temp_dir: Path) -> DownloadResult:
        import instaloader

        if not parsed_url.shortcode:
            raise DownloadError("缺少 Instagram 短码。")
        post = instaloader.Post.from_shortcode(loader.context, parsed_url.shortcode)
        session = self._get_session(loader)
        items: list[MediaItem] = []
        if post.typename == "GraphSidecar":
            for index, node in enumerate(post.get_sidecar_nodes(), start=1):
                media_url = node.video_url if node.is_video else node.display_url
                suffix = ".mp4" if node.is_video else ".jpg"
                target = temp_dir / f"{post.shortcode}_{index}{suffix}"
                self._download_file(session, media_url, target)
                items.append(
                    MediaItem(
                        media_id=f"{post.mediaid}_{index}",
                        shortcode=post.shortcode,
                        media_type=MediaType.VIDEO if node.is_video else MediaType.IMAGE,
                        local_path=target,
                        caption=post.caption,
                        source_url=parsed_url.normalized_url,
                        username=post.owner_username,
                        created_at=normalize_datetime(post.date_utc),
                    )
                )
        else:
            is_video = bool(post.is_video)
            media_url = post.video_url if is_video else post.url
            suffix = ".mp4" if is_video else ".jpg"
            target = temp_dir / f"{post.shortcode}{suffix}"
            self._download_file(session, media_url, target)
            items.append(
                MediaItem(
                    media_id=str(post.mediaid),
                    shortcode=post.shortcode,
                    media_type=MediaType.VIDEO if is_video else MediaType.IMAGE,
                    local_path=target,
                    caption=post.caption,
                    source_url=parsed_url.normalized_url,
                    username=post.owner_username,
                    created_at=normalize_datetime(post.date_utc),
                )
            )
        return DownloadResult(
            media_id=str(post.mediaid),
            shortcode=post.shortcode,
            username=post.owner_username,
            caption=post.caption,
            source_url=parsed_url.normalized_url,
            created_at=normalize_datetime(post.date_utc),
            items=items,
        )

    def _download_story(self, loader: Any, parsed_url: ParsedInstagramUrl, temp_dir: Path) -> DownloadResult:
        profile = self._load_profile(loader, parsed_url.username)
        session = self._get_session(loader)
        story_item = None
        for story in loader.get_stories(userids=[profile.userid]):
            for item in story.get_items():
                if str(item.mediaid) == str(parsed_url.story_media_id):
                    story_item = item
                    break
            if story_item is not None:
                break
        if story_item is None:
            raise DownloadError("未找到对应的 Story，可能已过期或当前会话无权限。")
        is_video = bool(story_item.is_video)
        media_url = story_item.video_url if is_video else story_item.url
        suffix = ".mp4" if is_video else ".jpg"
        target = temp_dir / f"story_{story_item.mediaid}{suffix}"
        self._download_file(session, media_url, target)
        item = MediaItem(
            media_id=str(story_item.mediaid),
            shortcode=None,
            media_type=MediaType.VIDEO if is_video else MediaType.IMAGE,
            local_path=target,
            caption=getattr(story_item, "caption", None),
            source_url=build_story_url(profile.username, str(story_item.mediaid)),
            username=profile.username,
            created_at=normalize_datetime(getattr(story_item, "date_utc", None)),
        )
        return DownloadResult(
            media_id=str(story_item.mediaid),
            shortcode=None,
            username=profile.username,
            caption=item.caption,
            source_url=item.source_url,
            created_at=item.created_at,
            items=[item],
        )

    def _fetch_feed_updates(
        self,
        loader: Any,
        username: str,
        checkpoint: SubscriptionCheckpoint | None,
        limit: int,
    ) -> list[RemoteMediaRef]:
        profile = self._load_profile(loader, username)
        refs: list[RemoteMediaRef] = []
        for post in profile.get_posts():
            created_at = normalize_datetime(post.date_utc)
            dedupe_key = post.shortcode or str(post.mediaid)
            if not self._is_newer_than_checkpoint(created_at, dedupe_key, checkpoint):
                break
            refs.append(
                RemoteMediaRef(
                    media_id=str(post.mediaid),
                    shortcode=post.shortcode,
                    source_url=build_post_url(post.shortcode),
                    username=profile.username,
                    created_at=created_at,
                    subscription_type=SubscriptionType.IG_FEED,
                )
            )
            if len(refs) >= limit:
                break
        refs.sort(key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.dedupe_key))
        return refs

    def _fetch_story_updates(
        self,
        loader: Any,
        username: str,
        checkpoint: SubscriptionCheckpoint | None,
        limit: int,
    ) -> list[RemoteMediaRef]:
        if not (self.config.instagram_username and self.config.instagram_session_file and self.config.instagram_session_file.exists()):
            raise ListingError("Story 订阅需要有效的 Instagram 会话文件。")
        profile = self._load_profile(loader, username)
        refs: list[RemoteMediaRef] = []
        for story in loader.get_stories(userids=[profile.userid]):
            for item in story.get_items():
                created_at = normalize_datetime(getattr(item, "date_utc", None))
                dedupe_key = str(item.mediaid)
                if self._is_newer_than_checkpoint(created_at, dedupe_key, checkpoint):
                    refs.append(
                        RemoteMediaRef(
                            media_id=str(item.mediaid),
                            shortcode=None,
                            source_url=build_story_url(profile.username, str(item.mediaid)),
                            username=profile.username,
                            created_at=created_at,
                            subscription_type=SubscriptionType.STORY,
                        )
                    )
        refs.sort(key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.dedupe_key))
        return refs[:limit]

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

    @staticmethod
    def _load_profile(loader: Any, username: str | None):
        if not username:
            raise DownloadError("缺少用户名。")
        import instaloader

        return instaloader.Profile.from_username(loader.context, username)

    @staticmethod
    def _get_session(loader: Any) -> requests.Session:
        session = getattr(loader.context, "_session", None)
        if isinstance(session, requests.Session):
            return session
        return requests.Session()

    def _download_file(self, session: requests.Session, media_url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with session.get(media_url, stream=True, timeout=self.config.download_timeout_seconds) as response:
            response.raise_for_status()
            with target.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        fh.write(chunk)
        logger.info("Instaloader 下载文件完成: %s", target)

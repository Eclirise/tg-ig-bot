from __future__ import annotations

from pathlib import Path

import pytest

import app.downloader.router as router_module
from app.downloader.base import DownloadError, DownloaderBackend, ListingError
from app.downloader.router import DownloaderRouter
from app.downloader.types import DownloadResult, MediaItem, RemoteMediaRef
from app.models import MediaType, SubscriptionType


class StubBackend(DownloaderBackend):
    def __init__(
        self,
        name: str,
        *,
        download_error: Exception | None = None,
        listing_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.download_error = download_error
        self.listing_error = listing_error
        self.supports_listing = True
        self.download_calls = 0
        self.fetch_calls = 0
        self.return_empty_result = False
        self.return_missing_file = False

    async def download_url(self, url: str, parsed_url, temp_dir: Path) -> DownloadResult:
        self.download_calls += 1
        if self.download_error is not None:
            raise self.download_error
        if self.return_empty_result:
            return DownloadResult(
                media_id=self.name,
                shortcode="abc",
                username="example",
                caption=None,
                source_url=url,
                created_at=None,
                items=[],
            )
        if self.return_missing_file:
            path = temp_dir / "missing.jpg"
            return DownloadResult(
                media_id=self.name,
                shortcode="abc",
                username="example",
                caption=None,
                source_url=url,
                created_at=None,
                items=[
                    MediaItem(
                        media_id=self.name,
                        shortcode="abc",
                        media_type=MediaType.IMAGE,
                        local_path=path,
                        caption=None,
                        source_url=url,
                        username="example",
                        created_at=None,
                    )
                ],
            )
        path = temp_dir / f"{self.name}.jpg"
        return DownloadResult(
            media_id=self.name,
            shortcode="abc",
            username="example",
            caption=None,
            source_url=url,
            created_at=None,
            items=[
                MediaItem(
                    media_id=self.name,
                    shortcode="abc",
                    media_type=MediaType.IMAGE,
                    local_path=path,
                    caption=None,
                    source_url=url,
                    username="example",
                    created_at=None,
                )
            ],
        )

    async def fetch_updates(self, username: str, subscription_type: SubscriptionType, checkpoint, *, limit: int) -> list[RemoteMediaRef]:
        self.fetch_calls += 1
        if self.listing_error is not None:
            raise self.listing_error
        return [
            RemoteMediaRef(
                media_id="1",
                shortcode="abc",
                source_url="https://www.instagram.com/p/abc/",
                username=username,
                created_at=None,
                subscription_type=subscription_type,
            )
        ]


async def single_try(func, **kwargs):
    return await func()


@pytest.mark.asyncio()
async def test_router_download_fallback_to_second_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "async_retry", single_try)
    first = StubBackend("instaloader", download_error=DownloadError("instaloader fail"))
    second = StubBackend("gallery-dl")
    third = StubBackend("yt-dlp")
    router = DownloaderRouter([first, second, third], temp_root=tmp_path, max_concurrent_downloads=1)
    result = await router.download("https://www.instagram.com/p/abc/")
    assert result.backend_name == "gallery-dl"
    assert first.download_calls == 1
    assert second.download_calls == 1
    assert third.download_calls == 0


@pytest.mark.asyncio()
async def test_router_listing_fallback_to_second_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "async_retry", single_try)
    first = StubBackend("instaloader", listing_error=ListingError("instaloader list fail"))
    second = StubBackend("gallery-dl")
    router = DownloaderRouter([first, second], temp_root=tmp_path, max_concurrent_downloads=1)
    refs = await router.fetch_updates("example", SubscriptionType.IG_FEED, None, limit=3)
    assert len(refs) == 1
    assert first.fetch_calls == 1
    assert second.fetch_calls == 1


@pytest.mark.asyncio()
async def test_router_rate_limit_stops_backend_fallback_and_sets_cooldown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "async_retry", single_try)
    first = StubBackend("instaloader", download_error=DownloadError("429 Too Many Requests"))
    second = StubBackend("gallery-dl")
    router = DownloaderRouter(
        [first, second],
        temp_root=tmp_path,
        max_concurrent_downloads=1,
        rate_limit_cooldown_min_seconds=60,
        rate_limit_cooldown_max_seconds=60,
    )
    with pytest.raises(DownloadError):
        await router.download("https://www.instagram.com/p/abc/")
    assert first.download_calls == 1
    assert second.download_calls == 0
    assert router.remaining_rate_limit_cooldown_seconds() > 0


@pytest.mark.asyncio()
async def test_router_youtube_download_uses_ytdlp_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "async_retry", single_try)
    first = StubBackend("instaloader")
    second = StubBackend("gallery-dl")
    third = StubBackend("yt-dlp")
    router = DownloaderRouter([first, second, third], temp_root=tmp_path, max_concurrent_downloads=1)

    result = await router.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert result.backend_name == "yt-dlp"
    assert first.download_calls == 0
    assert second.download_calls == 0
    assert third.download_calls == 1


@pytest.mark.asyncio()
async def test_router_rejects_empty_download_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "async_retry", single_try)
    backend = StubBackend("instaloader")
    backend.return_empty_result = True
    router = DownloaderRouter([backend], temp_root=tmp_path, max_concurrent_downloads=1)

    with pytest.raises(DownloadError, match="空下载结果"):
        await router.download("https://www.instagram.com/p/abc/")


@pytest.mark.asyncio()
async def test_router_rejects_missing_downloaded_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(router_module, "async_retry", single_try)
    backend = StubBackend("instaloader")
    backend.return_missing_file = True
    router = DownloaderRouter([backend], temp_root=tmp_path, max_concurrent_downloads=1)

    with pytest.raises(DownloadError, match="不存在的媒体文件"):
        await router.download("https://www.instagram.com/p/abc/")

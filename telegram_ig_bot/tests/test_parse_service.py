from __future__ import annotations

from pathlib import Path

import pytest

from app.downloader.types import DownloadResult, MediaItem
from app.models import MediaType
from app.services.parse_service import ParseService


class StubRouter:
    def __init__(self, result: DownloadResult) -> None:
        self.result = result

    async def download(self, url: str) -> DownloadResult:
        return self.result


class StubSenderService:
    def __init__(self) -> None:
        self.progress_updates: list[tuple[int, int]] = []

    async def send_download(self, bot, chat_id: int, result: DownloadResult, *, reply_to_message_id=None, progress_callback=None) -> bool:
        if progress_callback is not None:
            await progress_callback(1, 1)
            self.progress_updates.append((1, 1))
        return True


class StubStatsService:
    def __init__(self) -> None:
        self.calls = 0

    def record_delivery(self, chat_id: int, result: DownloadResult, *, count_parse_request: bool) -> None:
        self.calls += 1


class StubMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class StubBot:
    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.deleted_ids: list[int] = []
        self._next_message_id = 100

    async def send_message(self, chat_id: int, text: str):
        self.sent_texts.append(text)
        self._next_message_id += 1
        return StubMessage(self._next_message_id)

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_ids.append(message_id)


@pytest.mark.asyncio()
async def test_parse_service_replaces_progress_and_clears_on_success(tmp_path: Path) -> None:
    item = MediaItem(
        media_id="1",
        shortcode="abc",
        media_type=MediaType.VIDEO,
        local_path=tmp_path / "video.mp4",
        caption=None,
        source_url="https://www.instagram.com/reel/abc/",
        username="example",
        created_at=None,
    )
    result = DownloadResult(
        media_id="1",
        shortcode="abc",
        username="example",
        caption=None,
        source_url="https://www.instagram.com/reel/abc/",
        created_at=None,
        items=[item],
    )
    bot = StubBot()
    sender = StubSenderService()
    stats = StubStatsService()
    service = ParseService(StubRouter(result), sender, stats)

    await service.parse_and_send(bot, 123, result.source_url, progress_message_id=10)

    assert bot.deleted_ids[0] == 10
    assert "正在下载 Instagram 内容" in bot.sent_texts[0]
    assert "下载完成，正在发送视频" in bot.sent_texts[1]
    assert "正在发送视频" in bot.sent_texts[2]
    assert bot.deleted_ids[-1] > 10
    assert stats.calls == 1
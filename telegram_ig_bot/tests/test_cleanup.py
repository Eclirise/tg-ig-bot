from __future__ import annotations

import pytest

from app.downloader.types import DownloadResult, MediaItem
from app.models import MediaType
from app.services.cleanup_service import CleanupService
from app.services.sender_service import SenderService


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int | None]] = []

    async def send_photo(self, chat_id: int, photo, caption=None, reply_to_message_id=None, allow_sending_without_reply=None):
        self.calls.append(("photo", chat_id, reply_to_message_id))

    async def send_video(
        self,
        chat_id: int,
        video,
        caption=None,
        supports_streaming=None,
        reply_to_message_id=None,
        allow_sending_without_reply=None,
    ):
        self.calls.append(("video", chat_id, reply_to_message_id))

    async def send_document(self, chat_id: int, document, caption=None, reply_to_message_id=None, allow_sending_without_reply=None):
        self.calls.append(("document", chat_id, reply_to_message_id))

    async def send_media_group(self, chat_id: int, media, reply_to_message_id=None, allow_sending_without_reply=None):
        self.calls.append(("media_group", chat_id, reply_to_message_id))


@pytest.mark.asyncio()
async def test_cleanup_after_send(config_factory, tmp_path) -> None:
    config = config_factory()
    cleanup_service = CleanupService()
    sender_service = SenderService(cleanup_service, config)
    temp_dir = tmp_path / "job"
    temp_dir.mkdir()
    image_path = temp_dir / "1.jpg"
    image_path.write_bytes(b"image")
    result = DownloadResult(
        media_id="1",
        shortcode="abc",
        username="example",
        caption="caption",
        source_url="https://www.instagram.com/p/abc/",
        created_at=None,
        temp_dir=temp_dir,
        items=[
            MediaItem(
                media_id="1",
                shortcode="abc",
                media_type=MediaType.IMAGE,
                local_path=image_path,
                caption="caption",
                source_url="https://www.instagram.com/p/abc/",
                username="example",
                created_at=None,
            )
        ],
    )
    bot = FakeBot()
    sent = await sender_service.send_download(bot, 100, result, reply_to_message_id=321)
    assert sent is True
    assert bot.calls == [("photo", 100, 321)]
    assert temp_dir.exists() is False

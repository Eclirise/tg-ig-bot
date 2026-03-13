from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.models import MediaType, SubscriptionType


@dataclass(slots=True)
class MediaItem:
    media_id: str
    shortcode: str | None
    media_type: MediaType
    local_path: Path
    caption: str | None
    source_url: str
    username: str | None
    created_at: datetime | None


@dataclass(slots=True)
class DownloadResult:
    media_id: str
    shortcode: str | None
    username: str | None
    caption: str | None
    source_url: str
    created_at: datetime | None
    items: list[MediaItem] = field(default_factory=list)
    backend_name: str = ""
    temp_dir: Path | None = None
    subscription_type: SubscriptionType | None = None

    @property
    def dedupe_key(self) -> str:
        return self.shortcode or self.media_id


@dataclass(slots=True)
class RemoteMediaRef:
    media_id: str
    shortcode: str | None
    source_url: str
    username: str
    created_at: datetime | None
    subscription_type: SubscriptionType

    @property
    def dedupe_key(self) -> str:
        return self.shortcode or self.media_id

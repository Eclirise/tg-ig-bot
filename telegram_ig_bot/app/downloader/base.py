from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.downloader.types import DownloadResult, RemoteMediaRef
from app.models import SubscriptionCheckpoint, SubscriptionType
from app.utils.url_parser import ParsedInstagramUrl


class DownloadError(RuntimeError):
    """Raised when a backend cannot download a target."""


class ListingError(RuntimeError):
    """Raised when a backend cannot enumerate profile updates."""


class DownloaderBackend(ABC):
    name: str
    supports_listing: bool = False

    @abstractmethod
    async def download_url(
        self,
        url: str,
        parsed_url: ParsedInstagramUrl,
        temp_dir: Path,
    ) -> DownloadResult:
        raise NotImplementedError

    async def fetch_updates(
        self,
        username: str,
        subscription_type: SubscriptionType,
        checkpoint: SubscriptionCheckpoint | None,
        *,
        limit: int,
    ) -> list[RemoteMediaRef]:
        raise ListingError(f"{self.name} 不支持订阅枚举。")

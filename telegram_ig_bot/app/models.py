from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import random
from zoneinfo import ZoneInfo


class SubscriptionType(str, Enum):
    IG_FEED = "ig_feed"
    STORY = "story"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    UNKNOWN = "unknown"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


@dataclass(slots=True)
class Subscription:
    id: int
    chat_id: int
    username: str
    ig_feed_enabled: bool
    story_enabled: bool
    status: SubscriptionStatus
    last_checked_at: datetime | None
    next_check_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.ig_feed_enabled or self.story_enabled


@dataclass(slots=True)
class SubscriptionCheckpoint:
    chat_id: int
    username: str
    subscription_type: SubscriptionType
    last_media_at: datetime | None
    last_media_key: str | None
    updated_at: datetime


@dataclass(slots=True)
class RuntimeGroup:
    chat_id: int
    title: str | None
    chat_type: str | None
    is_enabled: bool
    enabled_by: int | None
    enabled_at: datetime | None


@dataclass(slots=True)
class DailyStatsSummary:
    date_key: str
    chat_id: int
    parse_requests_success: int = 0
    feed_bundles_sent: int = 0
    story_bundles_sent: int = 0
    photos_sent: int = 0
    videos_sent: int = 0


@dataclass(slots=True)
class ChatSettings:
    chat_id: int
    poll_interval_minutes: int


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def compute_next_check_at(interval_minutes: int, *, now: datetime | None = None) -> datetime:
    current = normalize_datetime(now) or utcnow()
    jitter_seconds = random.randint(15, 45)
    return current + timedelta(minutes=interval_minutes, seconds=jitter_seconds)


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "未检查"
    current = normalize_datetime(value)
    return current.strftime("%Y-%m-%d %H:%M:%S UTC")


def local_date_key(timezone_name: str, *, now: datetime | None = None) -> str:
    current = normalize_datetime(now) or utcnow()
    zone = ZoneInfo(timezone_name)
    return current.astimezone(zone).strftime("%Y-%m-%d")

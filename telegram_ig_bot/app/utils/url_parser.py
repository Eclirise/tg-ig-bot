from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from urllib.parse import urlparse


class InstagramTargetType(str, Enum):
    POST = "post"
    REEL = "reel"
    STORY = "story"


SUPPORTED_DOMAINS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
    "www.instagr.am",
}


@dataclass(slots=True)
class ParsedInstagramUrl:
    original_url: str
    normalized_url: str
    target_type: InstagramTargetType
    shortcode: str | None = None
    username: str | None = None
    story_media_id: str | None = None

    @property
    def is_video_like(self) -> bool:
        return self.target_type == InstagramTargetType.REEL


def normalize_instagram_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("链接必须以 http:// 或 https:// 开头。")
    if parsed.netloc.lower() not in SUPPORTED_DOMAINS:
        raise ValueError("这不是有效的 Instagram 链接。")
    path = parsed.path.rstrip("/")
    if not path:
        raise ValueError("Instagram 链接路径不能为空。")
    return f"https://www.instagram.com{path}/"


def parse_instagram_url(url: str) -> ParsedInstagramUrl:
    normalized = normalize_instagram_url(url)
    parsed = urlparse(normalized)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"p", "post", "tv"}:
        shortcode = parts[1]
        return ParsedInstagramUrl(
            original_url=url,
            normalized_url=f"https://www.instagram.com/p/{shortcode}/",
            target_type=InstagramTargetType.POST,
            shortcode=shortcode,
        )
    if len(parts) >= 2 and parts[0] in {"reel", "reels"}:
        shortcode = parts[1]
        return ParsedInstagramUrl(
            original_url=url,
            normalized_url=f"https://www.instagram.com/reel/{shortcode}/",
            target_type=InstagramTargetType.REEL,
            shortcode=shortcode,
        )
    if len(parts) >= 3 and parts[0] == "stories":
        username = parts[1].strip("@").lower()
        story_media_id = parts[2]
        if not username or not story_media_id:
            raise ValueError("Story 链接不完整。")
        return ParsedInstagramUrl(
            original_url=url,
            normalized_url=f"https://www.instagram.com/stories/{username}/{story_media_id}/",
            target_type=InstagramTargetType.STORY,
            username=username,
            story_media_id=story_media_id,
        )
    raise ValueError("当前仅支持帖子、Reel 和 Story 链接。")


def normalize_username(value: str) -> str:
    username = value.strip().strip("/").strip("@").lower()
    if not username:
        raise ValueError("用户名不能为空。")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._")
    if any(char not in allowed for char in username):
        raise ValueError("用户名格式无效，只能包含字母、数字、点和下划线。")
    return username


def extract_instagram_url(text: str | None) -> str | None:
    if not text:
        return None
    for candidate in re.findall(r"https?://\S+", text):
        try:
            parse_instagram_url(candidate)
            return candidate
        except ValueError:
            continue
    return None


def build_post_url(shortcode: str) -> str:
    return f"https://www.instagram.com/p/{shortcode}/"


def build_reel_url(shortcode: str) -> str:
    return f"https://www.instagram.com/reel/{shortcode}/"


def build_story_url(username: str, media_id: str) -> str:
    return f"https://www.instagram.com/stories/{username}/{media_id}/"

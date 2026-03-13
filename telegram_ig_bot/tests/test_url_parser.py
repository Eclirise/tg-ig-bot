from app.utils.url_parser import (
    InstagramTargetType,
    MediaPlatform,
    extract_instagram_url,
    extract_supported_url,
    parse_instagram_url,
    parse_supported_url,
    parse_youtube_url,
)


def test_parse_reel_url() -> None:
    parsed = parse_instagram_url("https://www.instagram.com/reel/ABC123/?utm_source=ig_web_copy_link")
    assert parsed.target_type == InstagramTargetType.REEL
    assert parsed.shortcode == "ABC123"


def test_parse_story_url() -> None:
    parsed = parse_instagram_url("https://www.instagram.com/stories/example.user/123456789/")
    assert parsed.target_type == InstagramTargetType.STORY
    assert parsed.username == "example.user"
    assert parsed.story_media_id == "123456789"


def test_extract_instagram_url_from_text() -> None:
    text = "看看这个 https://www.instagram.com/p/XYZ987/ 先"
    assert extract_instagram_url(text) == "https://www.instagram.com/p/XYZ987/"


def test_parse_youtube_watch_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1")
    assert parsed.platform == MediaPlatform.YOUTUBE
    assert parsed.video_id == "dQw4w9WgXcQ"


def test_parse_supported_url_accepts_youtube_short_link() -> None:
    parsed = parse_supported_url("https://youtu.be/dQw4w9WgXcQ")
    assert parsed.platform == MediaPlatform.YOUTUBE
    assert parsed.normalized_url == "https://youtu.be/dQw4w9WgXcQ"


def test_extract_supported_url_from_text() -> None:
    text = "看这个 https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert extract_supported_url(text) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

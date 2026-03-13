from app.utils.url_parser import InstagramTargetType, extract_instagram_url, parse_instagram_url


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

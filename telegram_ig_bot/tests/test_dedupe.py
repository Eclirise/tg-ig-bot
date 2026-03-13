from app.db import Database
from app.models import SubscriptionStatus


def test_dedupe_is_strict_per_subscription_type(tmp_path) -> None:
    db = Database(tmp_path / "dedupe.sqlite3")
    db.initialize()
    db.upsert_subscription(
        1,
        "example",
        ig_feed_enabled=True,
        story_enabled=True,
        status=SubscriptionStatus.ACTIVE,
        next_check_at=None,
    )
    db.record_delivered(1, "example", "media-key", "ig_feed")
    assert db.was_delivered(1, "media-key", "ig_feed") is True
    assert db.was_delivered(1, "media-key", "story") is False

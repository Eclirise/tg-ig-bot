from datetime import datetime, timezone

from app.db import Database
from app.services.auth_service import AccessService
from app.services.settings_service import SettingsService
from app.services.stats_service import StatsService
from app.services.subscription_service import SubscriptionService


def test_rate_limit_backoff_is_longer_than_normal_interval(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "rate_limit.sqlite3")
    db.initialize()
    service = SubscriptionService(
        db,
        SettingsService(db, config),
        router=None,  # type: ignore[arg-type]
        sender_service=None,  # type: ignore[arg-type]
        stats_service=StatsService(db, config),
        access_service=AccessService(db, config),
        config=config,
    )
    now = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc)
    default_next = datetime(2026, 3, 13, 0, 10, tzinfo=timezone.utc)
    delayed = service._compute_next_check_at_after_run(
        now=now,
        default_next_check_at=default_next,
        error_messages=["IG动态: 429 Too Many Requests"],
    )
    assert delayed > default_next

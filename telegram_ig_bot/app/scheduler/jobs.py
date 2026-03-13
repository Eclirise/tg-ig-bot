from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import AppConfig
from app.services.subscription_service import SubscriptionService


def create_scheduler(config: AppConfig, subscription_service: SubscriptionService, bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    scheduler.add_job(
        subscription_service.poll_due_subscriptions,
        trigger="interval",
        seconds=config.scheduler_tick_seconds,
        args=[bot],
        id="subscription-poller",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
        next_run_time=datetime.now(tz=timezone.utc),
    )
    return scheduler

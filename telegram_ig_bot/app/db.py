from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.models import (
    DailyStatsSummary,
    RuntimeGroup,
    Subscription,
    SubscriptionCheckpoint,
    SubscriptionStatus,
    SubscriptionType,
    parse_iso,
    to_iso,
    utcnow,
)


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    type TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 0,
    enabled_by INTEGER,
    enabled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    ig_feed_enabled INTEGER NOT NULL DEFAULT 0,
    story_enabled INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    last_checked_at TEXT,
    next_check_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(chat_id, username)
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_next_check_at
    ON subscriptions(next_check_at);

CREATE TABLE IF NOT EXISTS subscription_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    subscription_type TEXT NOT NULL,
    last_media_at TEXT,
    last_media_key TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(chat_id, username, subscription_type)
);

CREATE TABLE IF NOT EXISTS delivered_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    subscription_type TEXT NOT NULL,
    media_key TEXT NOT NULL,
    delivered_at TEXT NOT NULL,
    UNIQUE(chat_id, media_key, subscription_type)
);

CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(chat_id, key)
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date_key TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    stat_key TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(date_key, chat_id, stat_key)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000;")
        return connection

    def initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def ensure_chat(self, chat_id: int, title: str | None, chat_type: str | None) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO chats(chat_id, title, type, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (chat_id, title, chat_type, now, now),
            )
            conn.execute(
                """
                UPDATE chats
                SET title = ?,
                    type = ?,
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (title, chat_type, now, chat_id),
            )

    def set_chat_enabled(
        self,
        chat_id: int,
        title: str | None,
        chat_type: str | None,
        *,
        enabled: bool,
        enabled_by: int | None,
    ) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO chats(
                    chat_id,
                    title,
                    type,
                    is_enabled,
                    enabled_by,
                    enabled_at,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    title,
                    chat_type,
                    int(enabled),
                    enabled_by,
                    now if enabled else None,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE chats
                SET title = ?,
                    type = ?,
                    is_enabled = ?,
                    enabled_by = ?,
                    enabled_at = ?,
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (title, chat_type, int(enabled), enabled_by, now if enabled else None, now, chat_id),
            )

    def is_chat_enabled(self, chat_id: int) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT is_enabled FROM chats WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return bool(row and row["is_enabled"])

    def get_chat(self, chat_id: int) -> RuntimeGroup | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chats WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return self._row_to_runtime_group(row) if row else None

    def list_enabled_groups(self) -> list[RuntimeGroup]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chats WHERE is_enabled = 1 ORDER BY title COLLATE NOCASE ASC, chat_id ASC"
            ).fetchall()
        return [self._row_to_runtime_group(row) for row in rows]

    def list_known_groups(self) -> list[RuntimeGroup]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chats
                WHERE chat_id < 0 OR type IN ('group', 'supergroup')
                ORDER BY is_enabled DESC, title COLLATE NOCASE ASC, chat_id ASC
                """
            ).fetchall()
        return [self._row_to_runtime_group(row) for row in rows]

    def upsert_subscription(
        self,
        chat_id: int,
        username: str,
        *,
        ig_feed_enabled: bool,
        story_enabled: bool,
        status: SubscriptionStatus,
        next_check_at: str | None,
    ) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO subscriptions(
                    chat_id,
                    username,
                    ig_feed_enabled,
                    story_enabled,
                    status,
                    next_check_at,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    username,
                    int(ig_feed_enabled),
                    int(story_enabled),
                    status.value,
                    next_check_at,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE subscriptions
                SET ig_feed_enabled = ?,
                    story_enabled = ?,
                    status = ?,
                    next_check_at = ?,
                    last_error = NULL,
                    updated_at = ?
                WHERE chat_id = ? AND username = ? COLLATE NOCASE
                """,
                (int(ig_feed_enabled), int(story_enabled), status.value, next_check_at, now, chat_id, username),
            )

    def get_subscription(self, chat_id: int, username: str) -> Subscription | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE chat_id = ? AND username = ? COLLATE NOCASE",
                (chat_id, username),
            ).fetchone()
        return self._row_to_subscription(row) if row else None

    def list_subscriptions(self, chat_id: int, *, include_inactive: bool = False) -> list[Subscription]:
        query = "SELECT * FROM subscriptions WHERE chat_id = ?"
        params: tuple[object, ...] = (chat_id,)
        if not include_inactive:
            query += " AND (ig_feed_enabled = 1 OR story_enabled = 1)"
        query += " ORDER BY username COLLATE NOCASE ASC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def list_due_subscriptions(self, now_iso: str, *, limit: int = 20) -> list[Subscription]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE (ig_feed_enabled = 1 OR story_enabled = 1)
                  AND next_check_at IS NOT NULL
                  AND next_check_at <= ?
                ORDER BY next_check_at ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def update_subscription_runtime(
        self,
        chat_id: int,
        username: str,
        *,
        status: SubscriptionStatus,
        last_checked_at: str | None,
        next_check_at: str | None,
        last_error: str | None,
    ) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET status = ?,
                    last_checked_at = ?,
                    next_check_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE chat_id = ? AND username = ? COLLATE NOCASE
                """,
                (status.value, last_checked_at, next_check_at, last_error, now, chat_id, username),
            )

    def reschedule_chat_subscriptions(self, chat_id: int, next_check_at: str) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET next_check_at = ?, updated_at = ?
                WHERE chat_id = ?
                  AND (ig_feed_enabled = 1 OR story_enabled = 1)
                """,
                (next_check_at, now, chat_id),
            )

    def set_checkpoint(
        self,
        chat_id: int,
        username: str,
        subscription_type: str,
        *,
        last_media_at: str | None,
        last_media_key: str | None,
    ) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO subscription_checkpoints(
                    chat_id,
                    username,
                    subscription_type,
                    last_media_at,
                    last_media_key,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (chat_id, username, subscription_type, last_media_at, last_media_key, now),
            )
            conn.execute(
                """
                UPDATE subscription_checkpoints
                SET last_media_at = ?,
                    last_media_key = ?,
                    updated_at = ?
                WHERE chat_id = ? AND username = ? COLLATE NOCASE AND subscription_type = ?
                """,
                (last_media_at, last_media_key, now, chat_id, username, subscription_type),
            )

    def get_checkpoint(
        self,
        chat_id: int,
        username: str,
        subscription_type: str,
    ) -> SubscriptionCheckpoint | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM subscription_checkpoints
                WHERE chat_id = ? AND username = ? COLLATE NOCASE AND subscription_type = ?
                """,
                (chat_id, username, subscription_type),
            ).fetchone()
        if row is None:
            return None
        return SubscriptionCheckpoint(
            chat_id=row["chat_id"],
            username=row["username"],
            subscription_type=SubscriptionType(row["subscription_type"]),
            last_media_at=parse_iso(row["last_media_at"]),
            last_media_key=row["last_media_key"],
            updated_at=parse_iso(row["updated_at"]) or utcnow(),
        )

    def was_delivered(self, chat_id: int, media_key: str, subscription_type: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM delivered_media
                WHERE chat_id = ? AND media_key = ? AND subscription_type = ?
                """,
                (chat_id, media_key, subscription_type),
            ).fetchone()
        return row is not None

    def record_delivered(self, chat_id: int, username: str, media_key: str, subscription_type: str) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO delivered_media(
                    chat_id,
                    username,
                    subscription_type,
                    media_key,
                    delivered_at
                )
                VALUES(?, ?, ?, ?, ?)
                """,
                (chat_id, username, subscription_type, media_key, now),
            )

    def set_setting(self, chat_id: int, key: str, value: str) -> None:
        now = to_iso(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO settings(chat_id, key, value, updated_at)
                VALUES(?, ?, ?, ?)
                """,
                (chat_id, key, value, now),
            )
            conn.execute(
                """
                UPDATE settings
                SET value = ?,
                    updated_at = ?
                WHERE chat_id = ? AND key = ?
                """,
                (value, now, chat_id, key),
            )

    def get_setting(self, chat_id: int, key: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
                (chat_id, key),
            ).fetchone()
        return row["value"] if row else None

    def count_active_subscriptions(self, *, chat_id: int | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM subscriptions WHERE (ig_feed_enabled = 1 OR story_enabled = 1)"
        params: tuple[object, ...] = ()
        if chat_id is not None:
            query += " AND chat_id = ?"
            params = (chat_id,)
        with self._lock, self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return int(row["count"]) if row else 0

    def increment_daily_stat(self, date_key: str, chat_id: int, stat_key: str, amount: int = 1) -> None:
        if amount == 0:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_stats(date_key, chat_id, stat_key, value)
                VALUES(?, ?, ?, 0)
                """,
                (date_key, chat_id, stat_key),
            )
            conn.execute(
                """
                UPDATE daily_stats
                SET value = value + ?
                WHERE date_key = ? AND chat_id = ? AND stat_key = ?
                """,
                (amount, date_key, chat_id, stat_key),
            )

    def get_daily_stats(self, date_key: str, *, chat_id: int = 0) -> DailyStatsSummary:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT stat_key, value FROM daily_stats WHERE date_key = ? AND chat_id = ?",
                (date_key, chat_id),
            ).fetchall()
        values = {row["stat_key"]: int(row["value"]) for row in rows}
        return DailyStatsSummary(
            date_key=date_key,
            chat_id=chat_id,
            parse_requests_success=values.get("parse_requests_success", 0),
            feed_bundles_sent=values.get("feed_bundles_sent", 0),
            story_bundles_sent=values.get("story_bundles_sent", 0),
            photos_sent=values.get("photos_sent", 0),
            videos_sent=values.get("videos_sent", 0),
        )

    @staticmethod
    def _row_to_runtime_group(row: sqlite3.Row) -> RuntimeGroup:
        return RuntimeGroup(
            chat_id=int(row["chat_id"]),
            title=row["title"],
            chat_type=row["type"],
            is_enabled=bool(row["is_enabled"]),
            enabled_by=row["enabled_by"],
            enabled_at=parse_iso(row["enabled_at"]),
        )

    @staticmethod
    def _row_to_subscription(row: sqlite3.Row) -> Subscription:
        return Subscription(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            username=str(row["username"]).lower(),
            ig_feed_enabled=bool(row["ig_feed_enabled"]),
            story_enabled=bool(row["story_enabled"]),
            status=SubscriptionStatus(row["status"]),
            last_checked_at=parse_iso(row["last_checked_at"]),
            next_check_at=parse_iso(row["next_check_at"]),
            last_error=row["last_error"],
            created_at=parse_iso(row["created_at"]) or utcnow(),
            updated_at=parse_iso(row["updated_at"]) or utcnow(),
        )

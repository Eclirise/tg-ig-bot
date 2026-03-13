from __future__ import annotations


RATE_LIMIT_MARKERS = (
    "429",
    "too many requests",
    "rate limit",
    "ratelimit",
    "please wait",
    "try again later",
    "feedback required",
    "throttl",
    "temporarily blocked",
)

AUTH_MARKERS = (
    "login required",
    "not logged in",
    "session",
    "cookie",
    "checkpoint_required",
    "challenge_required",
    "login",
    "authorization",
    "private account",
)


def normalize_error_text(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def is_rate_limit_error(text: str | None) -> bool:
    normalized = normalize_error_text(text)
    return any(marker in normalized for marker in RATE_LIMIT_MARKERS)


def is_auth_error(text: str | None) -> bool:
    normalized = normalize_error_text(text)
    return any(marker in normalized for marker in AUTH_MARKERS)

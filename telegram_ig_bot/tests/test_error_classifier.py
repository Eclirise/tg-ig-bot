from app.utils.error_classifier import is_auth_error, is_rate_limit_error


def test_rate_limit_classifier() -> None:
    assert is_rate_limit_error("429 Too Many Requests") is True
    assert is_rate_limit_error("Please wait a few minutes before you try again") is True
    assert is_rate_limit_error("normal error") is False


def test_auth_classifier() -> None:
    assert is_auth_error("login required to view this media") is True
    assert is_auth_error("session cookie expired") is True
    assert is_auth_error("temporary network error") is False

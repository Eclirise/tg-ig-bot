from app.db import Database
from app.services.auth_service import AccessService
from app.services.settings_service import SettingsService


def test_access_service_private_admin_and_enabled_group(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "access.sqlite3")
    db.initialize()
    service = AccessService(db, config)
    assert service.can_use_context(config.admin_tg_user_id, config.admin_tg_user_id, "private") is True
    assert service.can_use_context(999, 999, "private") is False
    db.set_chat_enabled(-100, "group", "supergroup", enabled=True, enabled_by=config.admin_tg_user_id)
    assert service.can_use_context(999, -100, "supergroup") is True


def test_admin_can_enable_known_private_user_by_id(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "access-private.sqlite3")
    db.initialize()
    db.ensure_chat(888, "allowed user", "private")
    service = AccessService(db, config)

    service.enable_known_private_user(888, config.admin_tg_user_id)
    assert service.can_use_context(888, 888, "private") is True

    service.disable_known_private_user(888, config.admin_tg_user_id)
    assert service.can_use_context(888, 888, "private") is False


def test_admin_private_permission_cannot_be_disabled(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "access-admin.sqlite3")
    db.initialize()
    service = AccessService(db, config)

    try:
        service.disable_known_private_user(config.admin_tg_user_id, config.admin_tg_user_id)
    except ValueError as exc:
        assert "管理员" in str(exc)
    else:
        raise AssertionError("expected ValueError when disabling admin private access")


def test_admin_can_enable_known_group_by_id(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "access-known.sqlite3")
    db.initialize()
    db.ensure_chat(-200, "???", "supergroup")
    service = AccessService(db, config)
    service.enable_known_group(-200, config.admin_tg_user_id)
    assert db.is_chat_enabled(-200) is True
    service.disable_known_group(-200, config.admin_tg_user_id)
    assert db.is_chat_enabled(-200) is False


def test_admin_target_chat_setting_round_trip(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "settings-target.sqlite3")
    db.initialize()
    service = SettingsService(db, config)

    assert service.get_admin_target_chat_id(config.admin_tg_user_id) is None

    service.set_admin_target_chat_id(config.admin_tg_user_id, -300)
    assert service.get_admin_target_chat_id(config.admin_tg_user_id) == -300

    service.clear_admin_target_chat_id(config.admin_tg_user_id)
    assert service.get_admin_target_chat_id(config.admin_tg_user_id) is None


def test_access_request_alert_setting_round_trip(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "settings-alerts.sqlite3")
    db.initialize()
    service = SettingsService(db, config)

    assert service.access_request_alerts_enabled() is True

    service.set_access_request_alerts_enabled(False)
    assert service.access_request_alerts_enabled() is False

    service.set_access_request_alerts_enabled(True)
    assert service.access_request_alerts_enabled() is True

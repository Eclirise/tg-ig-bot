from app.db import Database
from app.services.auth_service import AccessService


def test_access_service_private_admin_and_enabled_group(config_factory, tmp_path) -> None:
    config = config_factory()
    db = Database(tmp_path / "access.sqlite3")
    db.initialize()
    service = AccessService(db, config)
    assert service.can_use_context(config.admin_tg_user_id, config.admin_tg_user_id, "private") is True
    assert service.can_use_context(999, 999, "private") is False
    db.set_chat_enabled(-100, "group", "supergroup", enabled=True, enabled_by=config.admin_tg_user_id)
    assert service.can_use_context(999, -100, "supergroup") is True


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

from __future__ import annotations

from app.config import AppConfig
from app.db import Database


class AccessService:
    def __init__(self, db: Database, config: AppConfig) -> None:
        self.db = db
        self.config = config

    def is_admin(self, user_id: int | None) -> bool:
        return bool(user_id and user_id == self.config.admin_tg_user_id)

    def can_use_context(self, user_id: int | None, chat_id: int, chat_type: str) -> bool:
        if chat_type == "private":
            return self.is_admin(user_id) or self.db.is_chat_enabled(chat_id)
        return self.db.is_chat_enabled(chat_id)

    def can_deliver_chat(self, chat_id: int) -> bool:
        if chat_id == self.config.admin_tg_user_id:
            return True
        return self.db.is_chat_enabled(chat_id)

    def enable_group(self, chat_id: int, title: str | None, chat_type: str | None, actor_user_id: int) -> None:
        if not self.is_admin(actor_user_id):
            raise PermissionError("只有管理员可以执行这个操作。")
        self.db.set_chat_enabled(chat_id, title, chat_type, enabled=True, enabled_by=actor_user_id)

    def disable_group(self, chat_id: int, title: str | None, chat_type: str | None, actor_user_id: int) -> None:
        if not self.is_admin(actor_user_id):
            raise PermissionError("只有管理员可以执行这个操作。")
        self.db.set_chat_enabled(chat_id, title, chat_type, enabled=False, enabled_by=actor_user_id)

    def enable_known_group(self, chat_id: int, actor_user_id: int) -> None:
        if not self.is_admin(actor_user_id):
            raise PermissionError("只有管理员可以执行这个操作。")
        chat = self.db.get_chat(chat_id)
        if chat is None or (chat.chat_id >= 0 and chat.chat_type not in {"group", "supergroup"}):
            raise ValueError("没有找到这个群组，请先把 bot 拉进群里发送 /chatid。")
        self.db.set_chat_enabled(chat_id, chat.title, chat.chat_type, enabled=True, enabled_by=actor_user_id)

    def disable_known_group(self, chat_id: int, actor_user_id: int) -> None:
        if not self.is_admin(actor_user_id):
            raise PermissionError("只有管理员可以执行这个操作。")
        chat = self.db.get_chat(chat_id)
        if chat is None or (chat.chat_id >= 0 and chat.chat_type not in {"group", "supergroup"}):
            raise ValueError("没有找到这个群组，无法停用。")
        self.db.set_chat_enabled(chat_id, chat.title, chat.chat_type, enabled=False, enabled_by=actor_user_id)

    def enable_known_private_user(self, user_id: int, actor_user_id: int) -> None:
        if not self.is_admin(actor_user_id):
            raise PermissionError("只有管理员可以执行这个操作。")
        if user_id == self.config.admin_tg_user_id:
            return
        chat = self.db.get_chat(user_id)
        if chat is None or chat.chat_type != "private" or chat.chat_id <= 0:
            raise ValueError("没有找到这个私聊用户，请先让对方私聊 bot 并发送 /start。")
        self.db.set_chat_enabled(user_id, chat.title, chat.chat_type, enabled=True, enabled_by=actor_user_id)

    def disable_known_private_user(self, user_id: int, actor_user_id: int) -> None:
        if not self.is_admin(actor_user_id):
            raise PermissionError("只有管理员可以执行这个操作。")
        if user_id == self.config.admin_tg_user_id:
            raise ValueError("不能停用管理员自己的私聊权限。")
        chat = self.db.get_chat(user_id)
        if chat is None or chat.chat_type != "private" or chat.chat_id <= 0:
            raise ValueError("没有找到这个私聊用户，无法停用。")
        self.db.set_chat_enabled(user_id, chat.title, chat.chat_type, enabled=False, enabled_by=actor_user_id)

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from app.bot import keyboards, texts
from app.bot.states import InteractionState
from app.config import AppConfig
from app.db import Database
from app.services.auth_service import AccessService
from app.services.maintenance_service import MaintenanceService
from app.services.parse_service import ParseService
from app.services.settings_service import SettingsService
from app.services.stats_service import StatsService
from app.services.subscription_service import SubscriptionService
from app.utils.url_parser import extract_supported_url, normalize_username


logger = logging.getLogger(__name__)

ACTIVE_CHAT_MEMBER_STATUSES = {"member", "administrator", "creator"}
LEFT_CHAT_MEMBER_STATUSES = {"left", "kicked"}


@dataclass(slots=True)
class HandlerContext:
    config: AppConfig
    db: Database
    access_service: AccessService
    parse_service: ParseService
    subscription_service: SubscriptionService
    settings_service: SettingsService
    stats_service: StatsService
    maintenance_service: MaintenanceService
    background_tasks: set[asyncio.Task[Any]] = field(default_factory=set)


def build_router(context: HandlerContext) -> Router:
    router = Router(name="telegram-ig-bot")

    def track_task(coro: Any) -> None:
        task = asyncio.create_task(coro)
        context.background_tasks.add(task)

        def _finalize(finished: asyncio.Task[Any]) -> None:
            context.background_tasks.discard(finished)
            try:
                exception = finished.exception()
            except asyncio.CancelledError:
                return
            if exception is not None:
                logger.error(
                    "后台任务异常: %s",
                    exception,
                    exc_info=(type(exception), exception, exception.__traceback__),
                )

        task.add_done_callback(_finalize)

    def chat_display_name(chat: Any) -> str | None:
        if getattr(chat, "title", None):
            return chat.title
        full_name = " ".join(
            part for part in [getattr(chat, "first_name", None), getattr(chat, "last_name", None)] if part
        )
        return full_name or getattr(chat, "username", None)

    def chat_title(message: Message) -> str | None:
        return chat_display_name(message.chat)

    def format_user_label(user: Any) -> str:
        if user is None:
            return "未知用户"
        full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
        label = full_name or user.username or str(user.id)
        if user.username:
            return f"{label} (@{user.username})"
        return label

    def parse_chat_id_arg(command: CommandObject | None) -> int | None:
        if not command or not command.args:
            return None
        try:
            return int(command.args.strip())
        except (TypeError, ValueError):
            return None

    def parse_command_args(command: CommandObject | None) -> list[str]:
        if not command or not command.args:
            return []
        return [part for part in command.args.split() if part]

    def format_subscription_summary(prefix: str, username: str, feed_enabled: bool, story_enabled: bool) -> str:
        return (
            f"{prefix}：{username}\n"
            f"IG 动态：{'开' if feed_enabled else '关'}\n"
            f"Story：{'开' if story_enabled else '关'}"
        )

    def is_admin_private_context(user_id: int | None, chat_id: int, chat_type: str) -> bool:
        return bool(chat_type == "private" and chat_id > 0 and context.access_service.is_admin(user_id))

    def describe_chat_target(chat_id: int) -> str:
        chat = context.db.get_chat(chat_id)
        if chat is None:
            if chat_id == context.config.admin_tg_user_id:
                return f"管理员私聊 | chat_id={chat_id} | 类型=private | 状态=管理员"
            return f"未记录聊天 | chat_id={chat_id}"
        chat_type = chat.chat_type or "unknown"
        if chat.chat_id == context.config.admin_tg_user_id:
            status = "管理员"
        elif chat_type == "private":
            status = "已授权" if chat.is_enabled else "未授权"
        else:
            status = "已启用" if chat.is_enabled else "未启用"
        return f"{chat.title or '未命名聊天'} | chat_id={chat.chat_id} | 类型={chat_type} | 状态={status}"

    def resolve_managed_chat_id(
        *,
        user_id: int | None,
        source_chat_id: int,
        source_chat_type: str,
        state_data: dict[str, Any] | None = None,
    ) -> int:
        if state_data and state_data.get("target_chat_id") is not None:
            try:
                return int(state_data["target_chat_id"])
            except (TypeError, ValueError):
                pass
        if is_admin_private_context(user_id, source_chat_id, source_chat_type):
            selected = context.settings_service.get_admin_target_chat_id(source_chat_id)
            if selected is not None:
                return selected
        return source_chat_id

    def with_managed_scope_text(base_text: str, *, user_id: int | None, source_chat_id: int, source_chat_type: str) -> str:
        managed_chat_id = resolve_managed_chat_id(
            user_id=user_id,
            source_chat_id=source_chat_id,
            source_chat_type=source_chat_type,
        )
        if not is_admin_private_context(user_id, source_chat_id, source_chat_type):
            return base_text
        return f"{base_text}\n当前管理目标：{describe_chat_target(managed_chat_id)}"

    def is_cancel_text(text: str | None) -> bool:
        return (text or "").strip() == texts.CANCEL_ACTION_TEXT

    def summarize_message_preview(message: Message) -> str:
        preview = (message.text or message.caption or "").strip()
        if not preview:
            return "无附带文本"
        preview = preview.replace("\n", " ")
        return preview[:180] + ("…" if len(preview) > 180 else "")

    async def remember_chat(message: Message) -> bool:
        cached = getattr(message, "_chat_was_new", None)
        if cached is not None:
            return bool(cached)
        created = context.db.ensure_chat(message.chat.id, chat_title(message), str(message.chat.type))
        setattr(message, "_chat_was_new", created)
        return created

    async def send_admin_notification(bot, text: str, *, reply_markup=None) -> None:
        try:
            await bot.send_message(
                context.config.admin_tg_user_id,
                text[:3800],
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception("发送管理员通知失败")

    async def maybe_notify_new_private_user(message: Message, *, is_new_chat: bool) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not is_new_chat or str(message.chat.type) != "private" or context.access_service.is_admin(user_id):
            return
        if not context.settings_service.access_request_alerts_enabled():
            return
        user = message.from_user
        if user is None:
            return
        username_text = f"@{user.username}" if user.username else "无"
        text = "\n".join(
            [
                "【新私聊待审核】",
                f"用户：{format_user_label(user)}",
                f"user_id：{user.id}",
                f"username：{username_text}",
                f"首条消息：{summarize_message_preview(message)}",
                "",
                f"可直接使用 /allowuser {user.id} 或 /denyuser {user.id}",
            ]
        )
        await send_admin_notification(
            message.bot,
            text,
            reply_markup=keyboards.access_request_keyboard("user", user.id),
        )

    async def access_allowed(message: Message, *, admin_command: bool = False) -> bool:
        is_new_chat = await remember_chat(message)
        await maybe_notify_new_private_user(message, is_new_chat=is_new_chat)
        user_id = message.from_user.id if message.from_user else None
        if admin_command:
            if context.access_service.is_admin(user_id):
                return True
            await message.answer(texts.ADMIN_ONLY_TEXT)
            return False
        if context.access_service.can_use_context(user_id, message.chat.id, str(message.chat.type)):
            return True
        if str(message.chat.type) == "private":
            await message.answer(texts.PRIVATE_DENIED_TEXT)
        else:
            await message.answer(texts.GROUP_DENIED_TEXT)
        return False

    async def callback_access_allowed(query: CallbackQuery, *, admin_command: bool = False) -> bool:
        if not query.message:
            return False
        fake_message = query.message
        user_id = query.from_user.id if query.from_user else None
        context.db.ensure_chat(fake_message.chat.id, chat_display_name(fake_message.chat), str(fake_message.chat.type))
        if admin_command:
            if context.access_service.is_admin(user_id):
                return True
            await query.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
            return False
        if context.access_service.can_use_context(user_id, fake_message.chat.id, str(fake_message.chat.type)):
            return True
        await query.answer(
            texts.GROUP_DENIED_TEXT if str(fake_message.chat.type) != "private" else texts.PRIVATE_DENIED_TEXT,
            show_alert=True,
        )
        return False

    async def begin_parse(message: Message, url: str) -> None:
        progress = await message.answer("已收到链接，准备加入解析队列。")
        track_task(
            context.parse_service.parse_and_send(
                message.bot,
                message.chat.id,
                url,
                progress_message_id=progress.message_id,
                reply_to_message_id=message.message_id if str(message.chat.type) != "private" else None,
            )
        )

    def resolve_url_from_message(message: Message, command: CommandObject | None = None) -> str | None:
        if command and command.args:
            return command.args.strip()
        direct = extract_supported_url(message.text or message.caption)
        if direct:
            return direct
        if message.reply_to_message:
            replied = extract_supported_url(message.reply_to_message.text or message.reply_to_message.caption)
            if replied:
                return replied
        return None

    async def show_runtime_status(message: Message) -> None:
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        snapshot = context.settings_service.get_runtime_snapshot(managed_chat_id)
        stats = context.stats_service.get_today_summary(chat_id=managed_chat_id)
        await message.answer(
            with_managed_scope_text(
                texts.format_runtime_status(snapshot, stats),
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.settings_menu_keyboard(),
        )

    async def show_access_alerts_status(message: Message) -> None:
        if str(message.chat.type) != "private":
            await message.answer("请在管理员私聊中使用 /accessalerts。")
            return
        enabled = context.settings_service.access_request_alerts_enabled()
        await message.answer(
            texts.format_access_alert_status(enabled),
            reply_markup=keyboards.access_alerts_keyboard(enabled),
        )

    async def notify_chat_access_change(bot, chat_id: int, text: str) -> None:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            logger.warning("通知聊天权限变更失败: chat_id=%s", chat_id)

    async def apply_review_action(query: CallbackQuery, kind: str, action: str, target_id: int) -> None:
        actor_user_id = query.from_user.id if query.from_user else 0
        allow = action == "allow"
        result_text = ""
        if kind == "user":
            if allow:
                context.access_service.enable_known_private_user(target_id, actor_user_id)
                await notify_chat_access_change(
                    query.bot,
                    target_id,
                    "管理员已允许你使用机器人，直接发送链接即可解析。",
                )
                result_text = f"已允许私聊用户 {target_id}"
            else:
                context.access_service.disable_known_private_user(target_id, actor_user_id)
                await notify_chat_access_change(
                    query.bot,
                    target_id,
                    "当前私聊权限未开启，如需使用请联系管理员。",
                )
                result_text = f"已拒绝私聊用户 {target_id}"
        elif kind == "group":
            chat = context.db.get_chat(target_id)
            if allow:
                context.access_service.enable_known_group(target_id, actor_user_id)
                context.subscription_service.reschedule_chat(target_id, immediate=True)
                await notify_chat_access_change(
                    query.bot,
                    target_id,
                    "管理员已启用本群，直接发送链接即可解析。",
                )
                result_text = f"已允许群组 {(chat.title if chat else None) or target_id}"
            else:
                context.access_service.disable_known_group(target_id, actor_user_id)
                context.db.reschedule_chat_subscriptions(target_id, None)
                await notify_chat_access_change(
                    query.bot,
                    target_id,
                    "管理员暂未启用本群。",
                )
                result_text = f"已拒绝群组 {(chat.title if chat else None) or target_id}"
        else:
            raise ValueError("未知审核类型。")
        if query.message and getattr(query.message, "text", None):
            await query.message.edit_text(f"{query.message.text}\n\n处理结果：{result_text}")
        await query.answer(result_text)

    async def handle_group_membership_change(event: ChatMemberUpdated) -> None:
        chat_type = str(event.chat.type)
        if chat_type not in {"group", "supergroup"}:
            return
        context.db.ensure_chat(event.chat.id, chat_display_name(event.chat), chat_type)
        old_status = getattr(event.old_chat_member, "status", None)
        new_status = getattr(event.new_chat_member, "status", None)
        if new_status in ACTIVE_CHAT_MEMBER_STATUSES and old_status not in ACTIVE_CHAT_MEMBER_STATUSES:
            if not context.settings_service.access_request_alerts_enabled():
                return
            text = "\n".join(
                [
                    "【Bot 被拉入新群】",
                    f"群名：{chat_display_name(event.chat) or '未命名群组'}",
                    f"chat_id：{event.chat.id}",
                    f"类型：{chat_type}",
                    f"操作者：{format_user_label(event.from_user)}",
                    "",
                    f"可直接使用 /allowgroup {event.chat.id} 或 /denygroup {event.chat.id}",
                ]
            )
            await send_admin_notification(
                event.bot,
                text,
                reply_markup=keyboards.access_request_keyboard("group", event.chat.id),
            )
            return
        if old_status in ACTIVE_CHAT_MEMBER_STATUSES and new_status in LEFT_CHAT_MEMBER_STATUSES:
            context.db.set_chat_enabled(
                event.chat.id,
                chat_display_name(event.chat),
                chat_type,
                enabled=False,
                enabled_by=None,
            )
            context.db.reschedule_chat_subscriptions(event.chat.id, None)
            text = "\n".join(
                [
                    "【Bot 已离开群组】",
                    f"群名：{chat_display_name(event.chat) or '未命名群组'}",
                    f"chat_id：{event.chat.id}",
                    "已自动停用该群并暂停订阅轮询。",
                ]
            )
            await send_admin_notification(event.bot, text)

    @router.message(Command("start"))
    async def start_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        await state.clear()
        if not await access_allowed(message):
            return
        help_tail = (
            f"\n\n{texts.ADMIN_HELP_TEXT}"
            if context.access_service.is_admin(message.from_user.id if message.from_user else None)
            else ""
        )
        await message.answer(texts.START_TEXT + help_tail, reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("help"))
    @router.message(F.text == "帮助")
    async def help_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        extra = (
            f"\n\n{texts.ADMIN_HELP_TEXT}"
            if context.access_service.is_admin(message.from_user.id if message.from_user else None)
            else ""
        )
        await message.answer(texts.HELP_TEXT + extra, reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("commands"))
    @router.message(F.text == "命令列表")
    async def commands_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        text = texts.COMMANDS_TEXT
        if not context.access_service.is_admin(message.from_user.id if message.from_user else None):
            text = text.split("\n\n管理员命令", 1)[0]
        await message.answer(text, reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("chatid"))
    async def chat_id_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        await message.answer(
            f"当前聊天信息\nchat_id: {message.chat.id}\n类型: {message.chat.type}\n标题: {chat_title(message) or '无标题'}"
        )

    @router.message(Command("stats"))
    async def stats_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        stats = context.stats_service.get_today_summary(chat_id=0)
        await message.answer(texts.format_stats(stats, title="全局统计"), reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("status"))
    @router.message(F.text == "运行状态")
    async def status_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        await show_runtime_status(message)

    @router.message(Command("accessalerts"))
    @router.message(F.text == "审核通知")
    async def access_alerts_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        await show_access_alerts_status(message)

    @router.message(Command("restart"))
    async def restart_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在管理员私聊中使用 /restart。")
            return
        await message.answer("收到重启请求，2 秒后自动退出并由 systemd 拉起。")
        track_task(context.maintenance_service.restart_application())

    @router.message(Command("update_tools"))
    async def update_tools_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在私聊中使用 /update_tools，避免群里误触发。")
            return
        progress = await message.answer("正在更新下载工具并执行自检，这可能需要 1 到 3 分钟。")
        try:
            result = await context.maintenance_service.update_downloader_tools()
        except Exception as exc:
            await progress.edit_text(f"下载工具更新失败。\n\n{exc}")
            return
        await progress.edit_text(result.render_message())

    @router.message(Command("listgroups"))
    async def list_groups_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        groups = context.db.list_enabled_groups()
        await message.answer(texts.format_enabled_groups(groups), reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("listusers"))
    async def list_users_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在私聊中使用 /listusers。")
            return
        users = context.db.list_enabled_private_users()
        await message.answer(texts.format_enabled_private_users(users), reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("knowngroups"))
    async def known_groups_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        groups = context.db.list_known_groups()
        await message.answer(texts.format_known_groups(groups), reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("knownusers"))
    async def known_users_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在私聊中使用 /knownusers。")
            return
        users = context.db.list_known_private_users()
        await message.answer(
            texts.format_known_private_users(users, admin_user_id=context.config.admin_tg_user_id),
            reply_markup=keyboards.main_menu_keyboard(),
        )

    @router.message(Command("allowgroup"))
    async def allow_group_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在私聊中使用 /allowgroup <chat_id>。")
            return
        chat_id = parse_chat_id_arg(command)
        if chat_id is None:
            await message.answer("用法：/allowgroup <chat_id>")
            return
        try:
            context.access_service.enable_known_group(chat_id, message.from_user.id if message.from_user else 0)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        context.subscription_service.reschedule_chat(chat_id, immediate=True)
        group = context.db.get_chat(chat_id)
        await message.answer(f"已允许群组：{group.title or chat_id}，chat_id={chat_id}。")

    @router.message(Command("denygroup"))
    async def deny_group_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在私聊中使用 /denygroup <chat_id>。")
            return
        chat_id = parse_chat_id_arg(command)
        if chat_id is None:
            await message.answer("用法：/denygroup <chat_id>")
            return
        try:
            context.access_service.disable_known_group(chat_id, message.from_user.id if message.from_user else 0)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        context.db.reschedule_chat_subscriptions(chat_id, None)
        group = context.db.get_chat(chat_id)
        await message.answer(f"已禁止群组：{(group.title if group else None) or chat_id}，chat_id={chat_id}。")

    @router.message(Command("allowuser"))
    async def allow_user_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在私聊中使用 /allowuser <user_id>。")
            return
        user_id = parse_chat_id_arg(command)
        if user_id is None or user_id <= 0:
            await message.answer("用法：/allowuser <user_id>")
            return
        try:
            context.access_service.enable_known_private_user(user_id, message.from_user.id if message.from_user else 0)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        user = context.db.get_chat(user_id)
        await message.answer(f"已允许私聊用户：{(user.title if user else None) or user_id}，user_id={user_id}。")

    @router.message(Command("denyuser"))
    async def deny_user_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("请在私聊中使用 /denyuser <user_id>。")
            return
        user_id = parse_chat_id_arg(command)
        if user_id is None or user_id <= 0:
            await message.answer("用法：/denyuser <user_id>")
            return
        try:
            context.access_service.disable_known_private_user(user_id, message.from_user.id if message.from_user else 0)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        user = context.db.get_chat(user_id)
        await message.answer(f"已禁止私聊用户：{(user.title if user else None) or user_id}，user_id={user_id}。")

    @router.message(Command("targetchat"))
    async def target_chat_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if not is_admin_private_context(
            message.from_user.id if message.from_user else None,
            message.chat.id,
            str(message.chat.type),
        ):
            await message.answer("请在管理员私聊中使用 /targetchat <chat_id>。")
            return
        target_chat_id = parse_chat_id_arg(command)
        if target_chat_id is None:
            current_target = context.settings_service.get_admin_target_chat_id(message.chat.id)
            if current_target is None:
                await message.answer("当前未设置远程管理目标，默认管理管理员自己的私聊。")
                return
            await message.answer(f"当前管理目标：{describe_chat_target(current_target)}")
            return
        target_chat = context.db.get_chat(target_chat_id)
        if target_chat is None and target_chat_id != context.config.admin_tg_user_id:
            await message.answer("没有找到这个聊天，请先让对方私聊 /start，或把 bot 拉进群后再试。")
            return
        context.settings_service.set_admin_target_chat_id(message.chat.id, target_chat_id)
        await message.answer(
            "当前管理目标已切换。\n"
            f"{describe_chat_target(target_chat_id)}\n"
            "之后私聊里的 /subs、/subadd、/submod、/unsubscribe 和运行状态都会作用到这个聊天。"
        )

    @router.message(Command("cleartarget"))
    async def clear_target_chat_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if not is_admin_private_context(
            message.from_user.id if message.from_user else None,
            message.chat.id,
            str(message.chat.type),
        ):
            await message.answer("请在管理员私聊中使用 /cleartarget。")
            return
        context.settings_service.clear_admin_target_chat_id(message.chat.id)
        await message.answer("已清除远程管理目标，后续私聊操作默认作用到管理员自己的私聊。")

    @router.message(Command("tg"))
    @router.message(Command("yt"))
    @router.message(Command("ig"))
    async def parse_command_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        url = resolve_url_from_message(message, command)
        if not url:
            await message.answer("请发送 Instagram 或 YouTube 链接，也可以直接把链接贴给机器人。")
            return
        await begin_parse(message, url)

    @router.message(Command("subs"))
    @router.message(F.text == "查看订阅")
    async def list_subscriptions_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        subscriptions = context.subscription_service.list_subscriptions(managed_chat_id)
        await message.answer(
            with_managed_scope_text(
                texts.format_subscription_list(subscriptions),
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(Command("subadd"))
    async def add_subscription_command_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        args = parse_command_args(command)
        if len(args) != 2:
            await message.answer("用法：/subadd <username> <feed|story|both>")
            return
        username, mode = args[0], args[1].lower()
        try:
            subscription = context.subscription_service.add_subscription(managed_chat_id, username, mode)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await message.answer(
            with_managed_scope_text(
                format_subscription_summary(
                    "已订阅",
                    subscription.username,
                    subscription.ig_feed_enabled,
                    subscription.story_enabled,
                ),
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(F.text == "新增订阅")
    async def add_subscription_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        await state.set_state(InteractionState.waiting_add_username)
        await state.update_data(target_chat_id=managed_chat_id)
        await message.answer(
            with_managed_scope_text(
                "请输入 Instagram 用户名。",
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(InteractionState.waiting_add_username)
    async def add_subscription_username_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        if is_cancel_text(message.text):
            await state.clear()
            await message.answer("已取消当前操作。", reply_markup=keyboards.main_menu_keyboard())
            return
        try:
            username = normalize_username(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(subscription_username=username)
        await message.answer("请选择订阅模式。", reply_markup=keyboards.add_subscription_mode_keyboard())

    @router.callback_query(F.data.startswith("subadd:"))
    async def add_subscription_callback(query: CallbackQuery, state: FSMContext) -> None:
        if not await callback_access_allowed(query):
            return
        action = (query.data or "").split(":", 1)[1]
        if action == "cancel":
            await state.clear()
            if query.message:
                await query.message.edit_text("已取消。")
            await query.answer()
            return
        data = await state.get_data()
        username = data.get("subscription_username")
        if not query.message:
            await query.answer("消息上下文已失效，请重试。", show_alert=True)
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=query.from_user.id if query.from_user else None,
            source_chat_id=query.message.chat.id,
            source_chat_type=str(query.message.chat.type),
            state_data=data,
        )
        if not username:
            await query.answer("缺少订阅用户名，请重新操作。", show_alert=True)
            return
        subscription = context.subscription_service.add_subscription(managed_chat_id, username, action)
        await state.clear()
        await query.message.edit_text(
            with_managed_scope_text(
                format_subscription_summary(
                    "已订阅",
                    subscription.username,
                    subscription.ig_feed_enabled,
                    subscription.story_enabled,
                ),
                user_id=query.from_user.id if query.from_user else None,
                source_chat_id=query.message.chat.id,
                source_chat_type=str(query.message.chat.type),
            )
        )
        await query.answer("已保存")

    @router.message(Command("submod"))
    async def modify_subscription_command_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        args = parse_command_args(command)
        if len(args) != 2:
            await message.answer(
                "用法：/submod <username> <only_feed|only_story|both|disable_feed|disable_story|unsubscribe>"
            )
            return
        username, action = args[0], args[1].lower()
        try:
            subscription = context.subscription_service.modify_subscription(managed_chat_id, username, action)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await message.answer(
            with_managed_scope_text(
                format_subscription_summary(
                    "已更新订阅",
                    subscription.username,
                    subscription.ig_feed_enabled,
                    subscription.story_enabled,
                ),
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(F.text == "修改订阅")
    async def modify_subscription_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        await state.set_state(InteractionState.waiting_modify_username)
        await state.update_data(target_chat_id=managed_chat_id)
        await message.answer(
            with_managed_scope_text(
                "请输入要修改的 Instagram 用户名。",
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(InteractionState.waiting_modify_username)
    async def modify_subscription_username_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        if is_cancel_text(message.text):
            await state.clear()
            await message.answer("已取消当前操作。", reply_markup=keyboards.main_menu_keyboard())
            return
        try:
            username = normalize_username(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        data = await state.get_data()
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
            state_data=data,
        )
        subscription = context.subscription_service.get_subscription(managed_chat_id, username)
        if subscription is None:
            await message.answer("未找到这个订阅。")
            return
        await state.update_data(subscription_username=username, target_chat_id=managed_chat_id)
        await message.answer("请选择新的订阅模式。", reply_markup=keyboards.modify_subscription_keyboard())

    @router.callback_query(F.data.startswith("submod:"))
    async def modify_subscription_callback(query: CallbackQuery, state: FSMContext) -> None:
        if not await callback_access_allowed(query):
            return
        action = (query.data or "").split(":", 1)[1]
        if not query.message:
            await query.answer("消息上下文已失效，请重试。", show_alert=True)
            return
        if action == "back":
            await state.clear()
            await query.message.edit_text("已返回。")
            await query.answer()
            return
        data = await state.get_data()
        username = data.get("subscription_username")
        managed_chat_id = resolve_managed_chat_id(
            user_id=query.from_user.id if query.from_user else None,
            source_chat_id=query.message.chat.id,
            source_chat_type=str(query.message.chat.type),
            state_data=data,
        )
        if not username:
            await query.answer("缺少订阅用户名，请重新操作。", show_alert=True)
            return
        try:
            subscription = context.subscription_service.modify_subscription(managed_chat_id, username, action)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await state.clear()
        await query.message.edit_text(
            with_managed_scope_text(
                format_subscription_summary(
                    "已更新订阅",
                    subscription.username,
                    subscription.ig_feed_enabled,
                    subscription.story_enabled,
                ),
                user_id=query.from_user.id if query.from_user else None,
                source_chat_id=query.message.chat.id,
                source_chat_type=str(query.message.chat.type),
            )
        )
        await query.answer("已保存")

    @router.message(Command("unsubscribe"))
    async def unsubscribe_command_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        args = parse_command_args(command)
        if len(args) != 1:
            await message.answer("用法：/unsubscribe <username>")
            return
        try:
            subscription = context.subscription_service.unsubscribe(managed_chat_id, args[0])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await message.answer(
            with_managed_scope_text(
                f"已退订：{subscription.username}",
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(F.text == "退订")
    async def unsubscribe_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        await state.set_state(InteractionState.waiting_unsubscribe_username)
        await state.update_data(target_chat_id=managed_chat_id)
        await message.answer(
            with_managed_scope_text(
                "请输入要退订的 Instagram 用户名。",
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(InteractionState.waiting_unsubscribe_username)
    async def unsubscribe_username_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        if is_cancel_text(message.text):
            await state.clear()
            await message.answer("已取消当前操作。", reply_markup=keyboards.main_menu_keyboard())
            return
        data = await state.get_data()
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
            state_data=data,
        )
        try:
            subscription = context.subscription_service.unsubscribe(managed_chat_id, message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.clear()
        await message.answer(
            with_managed_scope_text(
                f"已退订：{subscription.username}",
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.subscription_menu_keyboard(),
        )

    @router.message(Command("enable_here"))
    async def enable_here_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) == "private":
            await message.answer("私聊里不能使用 /enable_here。请在目标群里发送，或在私聊使用 /allowgroup <chat_id>。")
            return
        context.access_service.enable_group(
            message.chat.id,
            chat_title(message),
            str(message.chat.type),
            message.from_user.id if message.from_user else 0,
        )
        context.subscription_service.reschedule_chat(message.chat.id, immediate=True)
        await message.answer("当前群已启用，直接发送链接即可解析。")

    @router.message(Command("disable_here"))
    async def disable_here_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) == "private":
            await message.answer("私聊里不能使用 /disable_here。")
            return
        context.access_service.disable_group(
            message.chat.id,
            chat_title(message),
            str(message.chat.type),
            message.from_user.id if message.from_user else 0,
        )
        context.db.reschedule_chat_subscriptions(message.chat.id, None)
        await message.answer("当前群已停用，现有订阅也已暂停。")

    @router.message(F.text == "解析链接")
    async def parse_menu_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        await state.set_state(InteractionState.waiting_parse_url)
        await message.answer(texts.PARSE_PROMPT, reply_markup=keyboards.main_menu_keyboard())

    @router.message(InteractionState.waiting_parse_url)
    async def parse_waiting_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        if is_cancel_text(message.text):
            await state.clear()
            await message.answer("已取消当前操作。", reply_markup=keyboards.main_menu_keyboard())
            return
        url = resolve_url_from_message(message)
        if not url:
            await message.answer("请发送有效的 Instagram 或 YouTube 链接。")
            return
        await state.clear()
        await begin_parse(message, url)

    @router.message(Command("settarget"))
    @router.message(F.text == "设置管理目标")
    async def set_target_chat_prompt_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if not is_admin_private_context(
            message.from_user.id if message.from_user else None,
            message.chat.id,
            str(message.chat.type),
        ):
            await message.answer("请在管理员私聊中使用 /settarget 或 /targetchat。")
            return
        await state.set_state(InteractionState.waiting_target_chat_id)
        await message.answer(
            "请输入要管理的 chat_id 或 user_id。\n"
            "群组请先让 bot 入群，私聊用户请先让对方发送 /start。"
        )

    @router.message(InteractionState.waiting_target_chat_id)
    async def set_target_chat_input_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if is_cancel_text(message.text):
            await state.clear()
            await message.answer("已取消当前操作。", reply_markup=keyboards.main_menu_keyboard())
            return
        try:
            target_chat_id = int((message.text or "").strip())
        except ValueError:
            await message.answer("请输入有效的数字 chat_id 或 user_id。")
            return
        target_chat = context.db.get_chat(target_chat_id)
        if target_chat is None and target_chat_id != context.config.admin_tg_user_id:
            await message.answer("没有找到这个聊天，请先让对方私聊 /start，或把 bot 拉进群后再试。")
            return
        context.settings_service.set_admin_target_chat_id(message.chat.id, target_chat_id)
        await state.clear()
        await message.answer(f"当前管理目标已切换为：{describe_chat_target(target_chat_id)}")

    @router.message(F.text == "设置")
    async def settings_menu_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        await state.clear()
        await message.answer(
            with_managed_scope_text(
                texts.SETTINGS_MENU_TEXT,
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.settings_menu_keyboard(),
        )

    @router.message(F.text == "轮询频率")
    async def poll_frequency_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        managed_chat_id = resolve_managed_chat_id(
            user_id=message.from_user.id if message.from_user else None,
            source_chat_id=message.chat.id,
            source_chat_type=str(message.chat.type),
        )
        current = context.settings_service.get_poll_interval_minutes(managed_chat_id)
        await message.answer(
            with_managed_scope_text(
                f"当前轮询频率：{current} 分钟",
                user_id=message.from_user.id if message.from_user else None,
                source_chat_id=message.chat.id,
                source_chat_type=str(message.chat.type),
            ),
            reply_markup=keyboards.poll_interval_keyboard(current),
        )

    @router.callback_query(F.data.startswith("poll:"))
    async def poll_frequency_callback(query: CallbackQuery) -> None:
        if not await callback_access_allowed(query):
            return
        if not query.message:
            await query.answer("消息上下文已失效，请重试。", show_alert=True)
            return
        action = (query.data or "").split(":", 1)[1]
        if action == "back":
            await query.message.edit_text("已返回设置菜单。")
            await query.answer()
            return
        minutes = int(action)
        managed_chat_id = resolve_managed_chat_id(
            user_id=query.from_user.id if query.from_user else None,
            source_chat_id=query.message.chat.id,
            source_chat_type=str(query.message.chat.type),
        )
        context.settings_service.set_poll_interval_minutes(managed_chat_id, minutes)
        context.subscription_service.reschedule_chat(managed_chat_id, immediate=False)
        await query.message.edit_text(
            with_managed_scope_text(
                f"轮询频率已设置为 {minutes} 分钟",
                user_id=query.from_user.id if query.from_user else None,
                source_chat_id=query.message.chat.id,
                source_chat_type=str(query.message.chat.type),
            )
        )
        await query.answer("已保存")

    @router.callback_query(F.data.startswith("accessalerts:"))
    async def access_alerts_callback(query: CallbackQuery) -> None:
        if not await callback_access_allowed(query, admin_command=True):
            return
        if not query.message:
            await query.answer("消息上下文已失效，请重试。", show_alert=True)
            return
        enabled = (query.data or "").split(":", 1)[1] == "on"
        context.settings_service.set_access_request_alerts_enabled(enabled)
        await query.message.edit_text(
            texts.format_access_alert_status(enabled),
            reply_markup=keyboards.access_alerts_keyboard(enabled),
        )
        await query.answer("已保存")

    @router.callback_query(F.data.startswith("review:"))
    async def review_access_callback(query: CallbackQuery) -> None:
        if not await callback_access_allowed(query, admin_command=True):
            return
        parts = (query.data or "").split(":")
        if len(parts) != 4:
            await query.answer("回调数据无效。", show_alert=True)
            return
        _, kind, action, raw_target_id = parts
        try:
            target_id = int(raw_target_id)
        except ValueError:
            await query.answer("目标 ID 无效。", show_alert=True)
            return
        try:
            await apply_review_action(query, kind, action, target_id)
        except Exception as exc:
            await query.answer(str(exc), show_alert=True)

    @router.message(F.text == texts.CANCEL_ACTION_TEXT)
    async def cancel_action_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        await state.clear()
        await message.answer("已取消当前操作。", reply_markup=keyboards.main_menu_keyboard())

    @router.my_chat_member()
    async def my_chat_member_handler(event: ChatMemberUpdated) -> None:
        await handle_group_membership_change(event)

    @router.message()
    async def auto_parse_handler(message: Message, state: FSMContext) -> None:
        await remember_chat(message)
        if await state.get_state() is not None:
            return
        if not await access_allowed(message):
            return
        if (message.text or "").startswith("/") and not resolve_url_from_message(message):
            return
        url = resolve_url_from_message(message)
        if not url:
            return
        await begin_parse(message, url)

    return router

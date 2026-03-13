from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, texts
from app.bot.states import InteractionState
from app.config import AppConfig
from app.db import Database
from app.services.auth_service import AccessService
from app.services.parse_service import ParseService
from app.services.settings_service import SettingsService
from app.services.stats_service import StatsService
from app.services.subscription_service import SubscriptionService
from app.utils.url_parser import extract_instagram_url, normalize_username


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HandlerContext:
    config: AppConfig
    db: Database
    access_service: AccessService
    parse_service: ParseService
    subscription_service: SubscriptionService
    settings_service: SettingsService
    stats_service: StatsService
    background_tasks: set[asyncio.Task[Any]] = field(default_factory=set)


def build_router(context: HandlerContext) -> Router:
    router = Router(name="telegram-ig-bot")

    def track_task(coro: Any) -> None:
        task = asyncio.create_task(coro)
        context.background_tasks.add(task)
        task.add_done_callback(lambda finished: context.background_tasks.discard(finished))

    def chat_title(message: Message) -> str | None:
        if message.chat.title:
            return message.chat.title
        full_name = " ".join(part for part in [message.chat.first_name, message.chat.last_name] if part)
        return full_name or message.chat.username

    def parse_chat_id_arg(command: CommandObject | None) -> int | None:
        if not command or not command.args:
            return None
        try:
            return int(command.args.strip())
        except (TypeError, ValueError):
            return None

    async def remember_chat(message: Message) -> None:
        context.db.ensure_chat(message.chat.id, chat_title(message), str(message.chat.type))

    async def access_allowed(message: Message, *, admin_command: bool = False) -> bool:
        await remember_chat(message)
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
        context.db.ensure_chat(fake_message.chat.id, chat_title(fake_message), str(fake_message.chat.type))
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
        progress = await message.answer("???????????")
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
        direct = extract_instagram_url(message.text or message.caption)
        if direct:
            return direct
        if message.reply_to_message:
            replied = extract_instagram_url(message.reply_to_message.text or message.reply_to_message.caption)
            if replied:
                return replied
        return None

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
    @router.message(F.text == "??")
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

    @router.message(Command("chatid"))
    async def chat_id_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        await message.answer(
            f"??????\nchat_id?{message.chat.id}\n???{message.chat.type}\n???{chat_title(message) or '???'}"
        )

    @router.message(Command("stats"))
    async def stats_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        stats = context.stats_service.get_today_summary(chat_id=0)
        await message.answer(texts.format_stats(stats, title="??????"), reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("listgroups"))
    async def list_groups_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        groups = context.db.list_enabled_groups()
        await message.answer(texts.format_enabled_groups(groups), reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("knowngroups"))
    async def known_groups_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        groups = context.db.list_known_groups()
        await message.answer(texts.format_known_groups(groups), reply_markup=keyboards.main_menu_keyboard())

    @router.message(Command("allowgroup"))
    async def allow_group_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("??????? /allowgroup <chat_id>?")
            return
        chat_id = parse_chat_id_arg(command)
        if chat_id is None:
            await message.answer("???/allowgroup <chat_id>")
            return
        try:
            context.access_service.enable_known_group(chat_id, message.from_user.id if message.from_user else 0)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        context.subscription_service.reschedule_chat(chat_id, immediate=True)
        group = context.db.get_chat(chat_id)
        await message.answer(f"?????{group.title or chat_id}?chat_id={chat_id}?")

    @router.message(Command("denygroup"))
    async def deny_group_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) != "private":
            await message.answer("??????? /denygroup <chat_id>?")
            return
        chat_id = parse_chat_id_arg(command)
        if chat_id is None:
            await message.answer("???/denygroup <chat_id>")
            return
        try:
            context.access_service.disable_known_group(chat_id, message.from_user.id if message.from_user else 0)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        context.db.reschedule_chat_subscriptions(chat_id, None)
        group = context.db.get_chat(chat_id)
        await message.answer(f"?????{(group.title if group else None) or chat_id}?chat_id={chat_id}?")

    @router.message(Command("tg"))
    @router.message(Command("ig"))
    async def parse_command_handler(message: Message, command: CommandObject) -> None:
        await remember_chat(message)
        if not await access_allowed(message):
            return
        url = resolve_url_from_message(message, command)
        if not url:
            await message.answer("??????? Instagram ???????????????????? /ig?")
            return
        await begin_parse(message, url)

    @router.message(Command("enable_here"))
    async def enable_here_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) == "private":
            await message.answer("???????? /enable_here?????? /allowgroup <chat_id>?")
            return
        context.access_service.enable_group(
            message.chat.id,
            chat_title(message),
            str(message.chat.type),
            message.from_user.id if message.from_user else 0,
        )
        context.subscription_service.reschedule_chat(message.chat.id, immediate=True)
        await message.answer("??????????????? /ig?/tg ??????")

    @router.message(Command("disable_here"))
    async def disable_here_handler(message: Message) -> None:
        await remember_chat(message)
        if not await access_allowed(message, admin_command=True):
            return
        if str(message.chat.type) == "private":
            await message.answer("????????")
            return
        context.access_service.disable_group(
            message.chat.id,
            chat_title(message),
            str(message.chat.type),
            message.from_user.id if message.from_user else 0,
        )
        context.db.reschedule_chat_subscriptions(message.chat.id, None)
        await message.answer("???????????????????????????")

    @router.message(F.text == "????")
    async def parse_menu_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        await state.set_state(InteractionState.waiting_parse_url)
        await message.answer(texts.PARSE_PROMPT, reply_markup=keyboards.main_menu_keyboard())

    @router.message(InteractionState.waiting_parse_url)
    async def parse_waiting_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        if message.text == "?????":
            await state.clear()
            await message.answer(texts.START_TEXT, reply_markup=keyboards.main_menu_keyboard())
            return
        url = resolve_url_from_message(message)
        if not url:
            await message.answer("????? Instagram ?????????")
            return
        await state.clear()
        await begin_parse(message, url)

    @router.message(F.text == "????")
    async def subscription_menu_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        await state.clear()
        await message.answer(texts.SUBSCRIPTION_MENU_TEXT, reply_markup=keyboards.subscription_menu_keyboard())

    @router.message(F.text == "????")
    async def add_subscription_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        await state.set_state(InteractionState.waiting_add_username)
        await message.answer("??? Instagram ????", reply_markup=keyboards.subscription_menu_keyboard())

    @router.message(InteractionState.waiting_add_username)
    async def add_subscription_username_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        if message.text == "?????":
            await state.clear()
            await message.answer(texts.START_TEXT, reply_markup=keyboards.main_menu_keyboard())
            return
        try:
            username = normalize_username(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(subscription_username=username)
        await message.answer("????????", reply_markup=keyboards.add_subscription_mode_keyboard())

    @router.callback_query(F.data.startswith("subadd:"))
    async def add_subscription_callback(query: CallbackQuery, state: FSMContext) -> None:
        if not await callback_access_allowed(query):
            return
        action = (query.data or "").split(":", 1)[1]
        if action == "cancel":
            await state.clear()
            await query.message.edit_text("????????")
            await query.answer()
            return
        data = await state.get_data()
        username = data.get("subscription_username")
        if not username:
            await query.answer("???????????????", show_alert=True)
            return
        subscription = context.subscription_service.add_subscription(query.message.chat.id, username, action)
        await state.clear()
        await query.message.edit_text(
            f"??????{subscription.username}\nIG???{'?' if subscription.ig_feed_enabled else '?'}\nStory?{'?' if subscription.story_enabled else '?'}"
        )
        await query.answer("???")

    @router.message(F.text == "????")
    async def view_subscriptions_handler(message: Message) -> None:
        if not await access_allowed(message):
            return
        subscriptions = context.subscription_service.list_subscriptions(message.chat.id)
        await message.answer(texts.format_subscription_list(subscriptions), reply_markup=keyboards.subscription_menu_keyboard())

    @router.message(F.text == "????")
    async def modify_subscription_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        await state.set_state(InteractionState.waiting_modify_username)
        await message.answer("??????? Instagram ????", reply_markup=keyboards.subscription_menu_keyboard())

    @router.message(InteractionState.waiting_modify_username)
    async def modify_subscription_username_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        if message.text == "?????":
            await state.clear()
            await message.answer(texts.START_TEXT, reply_markup=keyboards.main_menu_keyboard())
            return
        try:
            username = normalize_username(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        subscription = context.subscription_service.get_subscription(message.chat.id, username)
        if subscription is None:
            await message.answer("?????????")
            return
        await state.update_data(subscription_username=username)
        await message.answer("????????", reply_markup=keyboards.modify_subscription_keyboard())

    @router.callback_query(F.data.startswith("submod:"))
    async def modify_subscription_callback(query: CallbackQuery, state: FSMContext) -> None:
        if not await callback_access_allowed(query):
            return
        action = (query.data or "").split(":", 1)[1]
        if action == "back":
            await state.clear()
            await query.message.edit_text("????")
            await query.answer()
            return
        data = await state.get_data()
        username = data.get("subscription_username")
        if not username:
            await query.answer("???????????????", show_alert=True)
            return
        try:
            subscription = context.subscription_service.modify_subscription(query.message.chat.id, username, action)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await state.clear()
        await query.message.edit_text(
            f"??????{subscription.username}\nIG???{'?' if subscription.ig_feed_enabled else '?'}\nStory?{'?' if subscription.story_enabled else '?'}"
        )
        await query.answer("???")

    @router.message(F.text == "??")
    async def unsubscribe_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        await state.set_state(InteractionState.waiting_unsubscribe_username)
        await message.answer("????????? Instagram ????", reply_markup=keyboards.subscription_menu_keyboard())

    @router.message(InteractionState.waiting_unsubscribe_username)
    async def unsubscribe_username_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        if message.text == "?????":
            await state.clear()
            await message.answer(texts.START_TEXT, reply_markup=keyboards.main_menu_keyboard())
            return
        try:
            subscription = context.subscription_service.unsubscribe(message.chat.id, message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.clear()
        await message.answer(f"??????{subscription.username}", reply_markup=keyboards.subscription_menu_keyboard())

    @router.message(F.text == "??")
    async def settings_menu_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        await state.clear()
        await message.answer(texts.SETTINGS_MENU_TEXT, reply_markup=keyboards.settings_menu_keyboard())

    @router.message(F.text == "????")
    async def poll_frequency_handler(message: Message) -> None:
        if not await access_allowed(message):
            return
        current = context.settings_service.get_poll_interval_minutes(message.chat.id)
        await message.answer(
            f"???????{current}???",
            reply_markup=keyboards.poll_interval_keyboard(current),
        )

    @router.callback_query(F.data.startswith("poll:"))
    async def poll_frequency_callback(query: CallbackQuery) -> None:
        if not await callback_access_allowed(query):
            return
        action = (query.data or "").split(":", 1)[1]
        if action == "back":
            await query.message.edit_text("????????")
            await query.answer()
            return
        minutes = int(action)
        context.settings_service.set_poll_interval_minutes(query.message.chat.id, minutes)
        context.subscription_service.reschedule_chat(query.message.chat.id, immediate=False)
        await query.message.edit_text(f"???????? {minutes} ???")
        await query.answer("???")

    @router.message(F.text == "??????")
    async def cleanup_policy_handler(message: Message) -> None:
        if not await access_allowed(message):
            return
        await message.answer(
            f"?????{context.settings_service.cleanup_policy_text()}",
            reply_markup=keyboards.settings_menu_keyboard(),
        )

    @router.message(F.text == "????")
    async def runtime_status_handler(message: Message) -> None:
        if not await access_allowed(message):
            return
        snapshot = context.settings_service.get_runtime_snapshot(message.chat.id)
        stats = context.stats_service.get_today_summary(chat_id=message.chat.id)
        await message.answer(texts.format_runtime_status(snapshot, stats), reply_markup=keyboards.settings_menu_keyboard())

    @router.message(F.text == "?????")
    async def back_to_main_handler(message: Message, state: FSMContext) -> None:
        if not await access_allowed(message):
            return
        await state.clear()
        await message.answer(texts.START_TEXT, reply_markup=keyboards.main_menu_keyboard())

    return router

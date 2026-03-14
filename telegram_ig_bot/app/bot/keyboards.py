from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.bot import texts


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="解析链接"), KeyboardButton(text="查看订阅")],
            [KeyboardButton(text="新增订阅"), KeyboardButton(text="运行状态")],
            [KeyboardButton(text="帮助"), KeyboardButton(text="命令列表")],
            [KeyboardButton(text="设置")],
        ],
        resize_keyboard=True,
    )


def subscription_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="查看订阅"), KeyboardButton(text="新增订阅")],
            [KeyboardButton(text="修改订阅"), KeyboardButton(text="退订")],
            [KeyboardButton(text=texts.CANCEL_ACTION_TEXT)],
        ],
        resize_keyboard=True,
    )


def settings_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="轮询频率"), KeyboardButton(text="审核通知")],
            [KeyboardButton(text="运行状态")],
            [KeyboardButton(text=texts.CANCEL_ACTION_TEXT)],
        ],
        resize_keyboard=True,
    )


def add_subscription_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="订阅 IG 动态", callback_data="subadd:feed")],
            [InlineKeyboardButton(text="订阅 Story", callback_data="subadd:story")],
            [InlineKeyboardButton(text="同时订阅两者", callback_data="subadd:both")],
            [InlineKeyboardButton(text="取消", callback_data="subadd:cancel")],
        ]
    )


def modify_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="只订阅 IG 动态", callback_data="submod:only_feed")],
            [InlineKeyboardButton(text="只订阅 Story", callback_data="submod:only_story")],
            [InlineKeyboardButton(text="同时订阅两者", callback_data="submod:both")],
            [InlineKeyboardButton(text="停止订阅 IG 动态", callback_data="submod:disable_feed")],
            [InlineKeyboardButton(text="停止订阅 Story", callback_data="submod:disable_story")],
            [InlineKeyboardButton(text="完全退订", callback_data="submod:unsubscribe")],
            [InlineKeyboardButton(text="返回", callback_data="submod:back")],
        ]
    )


def poll_interval_keyboard(current_minutes: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"5分钟{' ✓' if current_minutes == 5 else ''}",
                    callback_data="poll:5",
                ),
                InlineKeyboardButton(
                    text=f"10分钟{' ✓' if current_minutes == 10 else ''}",
                    callback_data="poll:10",
                ),
            ],
            [InlineKeyboardButton(text="返回", callback_data="poll:back")],
        ]
    )


def access_request_keyboard(kind: str, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="允许", callback_data=f"review:{kind}:allow:{chat_id}"),
                InlineKeyboardButton(text="拒绝", callback_data=f"review:{kind}:deny:{chat_id}"),
            ]
        ]
    )


def access_alerts_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"开启{' ✓' if enabled else ''}",
                    callback_data="accessalerts:on",
                ),
                InlineKeyboardButton(
                    text=f"关闭{' ✓' if not enabled else ''}",
                    callback_data="accessalerts:off",
                ),
            ]
        ]
    )

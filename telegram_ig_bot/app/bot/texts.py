from __future__ import annotations

from app.models import DailyStatsSummary, RuntimeGroup, Subscription, format_dt
from app.services.settings_service import RuntimeSnapshot


START_TEXT = """Instagram 下载机器人

发送 /tg <Instagram链接> 或 /ig <Instagram链接> 就可以解析下载。
也可以直接把链接发给机器人，机器人会自动识别。
如果要在群里使用，请先由管理员发送 /enable_here。"""

PARSE_PROMPT = "请发送 Instagram 链接，或直接输入 /tg <链接>、/ig <链接>。"
SUBSCRIPTION_MENU_TEXT = "订阅管理菜单"
SETTINGS_MENU_TEXT = "设置菜单，支持查看运行状态和轮询频率。"
HELP_TEXT = """帮助

1. 支持帖子、Reel、Story 链接，Story 需要有效会话。
2. 可直接发送 /tg <链接> 或 /ig <链接>。
3. 群里首次使用前，需要管理员发送 /enable_here。
4. 管理员可以用 /chatid、/knowngroups、/allowgroup、/denygroup 管理群权限。
5. 订阅支持 IG 动态 和 Story 两种模式。
6. 如果群里收不到命令，请去 BotFather 关闭 Privacy Mode。
7. 如果要抓取 Story 或受限内容，需要准备有效的 Instagram session / cookies。
8. 输入 /commands 可以查看完整命令列表。"""
ADMIN_HELP_TEXT = """管理员命令

/chatid 查看当前聊天 ID
/enable_here 在当前群启用机器人
/disable_here 在当前群停用机器人
/knowngroups 查看已记录群组
/allowgroup <chat_id> 允许指定群组
/denygroup <chat_id> 禁止指定群组
/listgroups 查看已启用群组
/stats 查看今日统计
/update_tools 更新 Instaloader / gallery-dl / yt-dlp 并自检
/commands 查看完整命令列表
/help 查看帮助"""
COMMANDS_TEXT = """命令列表

普通命令
/start 开始使用机器人
/help 查看帮助
/commands 查看完整命令列表
/ig <Instagram链接> 解析 Instagram 链接
/tg <Instagram链接> 解析 Instagram 链接

管理员命令
/chatid 查看当前聊天 ID
/enable_here 在当前群启用机器人
/disable_here 在当前群停用机器人
/knowngroups 查看已记录群组
/allowgroup <chat_id> 允许指定群组
/denygroup <chat_id> 禁止指定群组
/listgroups 查看已启用群组
/stats 查看今日统计
/update_tools 更新 Instaloader / gallery-dl / yt-dlp 并执行自检

说明
/update_tools 建议在私聊里由管理员执行。
工具更新完成后，建议在 VPS 上再执行一次 tg-ig-botctl restart，让 Instaloader 模块立即使用新版本。"""
PRIVATE_DENIED_TEXT = "当前私聊账号没有使用权限。"
GROUP_DENIED_TEXT = "当前群还没有启用机器人，请先由管理员发送 /enable_here，或在私聊用 /allowgroup <chat_id> 授权。"
ADMIN_ONLY_TEXT = "该命令仅管理员可用。"


def format_subscription_list(subscriptions: list[Subscription]) -> str:
    if not subscriptions:
        return "当前没有订阅。"
    lines = ["订阅列表"]
    for subscription in subscriptions:
        status_text = {
            "active": "启用",
            "inactive": "停用",
            "error": "异常",
        }.get(subscription.status.value, subscription.status.value)
        lines.append(
            "\n".join(
                [
                    f"账号：{subscription.username}",
                    f"IG 动态：{'开' if subscription.ig_feed_enabled else '关'}",
                    f"Story：{'开' if subscription.story_enabled else '关'}",
                    f"上次检查：{format_dt(subscription.last_checked_at)}",
                    f"状态：{status_text}" + (f"（{subscription.last_error}）" if subscription.last_error else ""),
                ]
            )
        )
    return "\n\n".join(lines)


def format_runtime_status(snapshot: RuntimeSnapshot, stats: DailyStatsSummary) -> str:
    return "\n".join(
        [
            "运行状态",
            "",
            f"当前轮询：{snapshot.poll_interval_minutes} 分钟",
            f"清理策略：{snapshot.cleanup_policy}",
            f"下载后端：{snapshot.backend_order}",
            f"当前聊天订阅数：{snapshot.chat_subscription_count}",
            f"全局订阅数：{snapshot.global_subscription_count}",
            "",
            format_stats(stats, title="今日统计"),
        ]
    )


def format_stats(stats: DailyStatsSummary, *, title: str = "统计信息") -> str:
    return "\n".join(
        [
            title,
            f"日期：{stats.date_key}",
            f"解析成功：{stats.parse_requests_success}",
            f"IG 动态发送数：{stats.feed_bundles_sent}",
            f"Story 发送数：{stats.story_bundles_sent}",
            f"图片发送数：{stats.photos_sent}",
            f"视频发送数：{stats.videos_sent}",
        ]
    )


def format_enabled_groups(groups: list[RuntimeGroup]) -> str:
    if not groups:
        return "当前没有启用的群组。"
    lines = ["已启用群组"]
    for group in groups:
        lines.append(
            f"{group.title or '未命名群组'} | chat_id={group.chat_id} | 启用时间={format_dt(group.enabled_at)}"
        )
    return "\n".join(lines)


def format_known_groups(groups: list[RuntimeGroup]) -> str:
    if not groups:
        return "当前还没有记录到任何群组，请先在群里发送 /chatid。"
    lines = ["已记录群组"]
    for group in groups:
        status = "已启用" if group.is_enabled else "未启用"
        lines.append(
            f"{group.title or '未命名群组'} | chat_id={group.chat_id} | 类型={group.chat_type or '未知'} | 状态={status}"
        )
    return "\n".join(lines)

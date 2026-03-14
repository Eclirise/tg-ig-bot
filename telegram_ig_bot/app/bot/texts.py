from __future__ import annotations

from app.models import DailyStatsSummary, RuntimeGroup, Subscription, format_dt
from app.services.settings_service import RuntimeSnapshot


CANCEL_ACTION_TEXT = "取消当前操作"

START_TEXT = """Instagram / YouTube 解析机器人

直接发送 Instagram 或 YouTube 链接即可开始解析。
也可以使用 /ig <链接> 触发解析，群里首次使用前请先由管理员发送 /enable_here。"""

PARSE_PROMPT = "请直接发送 Instagram 或 YouTube 链接。"
SUBSCRIPTION_MENU_TEXT = "订阅管理"
SETTINGS_MENU_TEXT = "设置菜单"
HELP_TEXT = """帮助

1. 直接发送 Instagram 或 YouTube 链接即可解析，不再需要 /tg 或 /yt 前缀。
2. 支持帖子、Reel、Story 链接；Story 和受限内容需要有效的 Instagram session / cookies。
3. 群里首次使用前，需要管理员发送 /enable_here，或在管理员私聊里执行 /allowgroup <chat_id>。
4. 订阅支持 IG 动态和 Story 两种模式，可用按钮或 /subadd、/submod、/unsubscribe 管理。
5. 新私聊用户、机器人被拉进新群时，管理员会收到审批通知，并可一键允许或拒绝。
6. 管理员可以通过 /accessalerts 或“审核通知”按钮随时开关审批提醒。
7. 如果群里收不到命令，请去 BotFather 关闭 Privacy Mode。"""

ADMIN_HELP_TEXT = """管理员命令

/chatid 查看当前聊天 ID
/enable_here 在当前群启用机器人
/disable_here 在当前群停用机器人
/knowngroups 查看已记录群组
/allowgroup <chat_id> 允许指定群组
/denygroup <chat_id> 禁止指定群组
/knownusers 查看已记录私聊用户
/listusers 查看已授权私聊用户
/allowuser <user_id> 允许指定私聊用户
/denyuser <user_id> 禁止指定私聊用户
/targetchat <chat_id> 切换私聊里的远程管理目标
/cleartarget 清除远程管理目标
/listgroups 查看已启用群组
/stats 查看今日统计
/status 查看运行状态
/accessalerts 查看或切换审批通知
/restart 重启机器人
/update_tools 更新 Instaloader / gallery-dl / yt-dlp 并自检
/subadd <username> <feed|story|both> 新增订阅
/submod <username> <only_feed|only_story|both|disable_feed|disable_story|unsubscribe> 修改订阅
/unsubscribe <username> 退订
/subs 查看当前聊天订阅
/commands 查看完整命令列表
/help 查看帮助"""

COMMANDS_TEXT = """命令列表

普通命令
/start 开始使用机器人
/help 查看帮助
/commands 查看完整命令列表
/ig <Instagram链接> 手动解析 Instagram 链接
/subs 查看当前聊天订阅
/subadd <username> <feed|story|both> 新增订阅
/submod <username> <only_feed|only_story|both|disable_feed|disable_story|unsubscribe> 修改订阅
/unsubscribe <username> 退订
/status 查看运行状态

管理员命令
/chatid 查看当前聊天 ID
/enable_here 在当前群启用机器人
/disable_here 在当前群停用机器人
/knowngroups 查看已记录群组
/allowgroup <chat_id> 允许指定群组
/denygroup <chat_id> 禁止指定群组
/knownusers 查看已记录私聊用户
/listusers 查看已授权私聊用户
/allowuser <user_id> 允许指定私聊用户
/denyuser <user_id> 禁止指定私聊用户
/targetchat <chat_id> 切换私聊里的远程管理目标
/cleartarget 清除远程管理目标
/listgroups 查看已启用群组
/stats 查看今日统计
/accessalerts 查看或切换审批通知
/restart 重启机器人
/update_tools 更新 Instaloader / gallery-dl / yt-dlp 并执行自检"""

PRIVATE_DENIED_TEXT = "当前私聊账号还没有使用权限，已记录你的账号，请等待管理员授权。"
GROUP_DENIED_TEXT = "当前群还没有启用机器人，请让管理员发送 /enable_here，或在管理员私聊执行 /allowgroup <chat_id>。"
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


def format_access_alert_status(enabled: bool) -> str:
    return "\n".join(
        [
            "审核通知设置",
            "",
            f"当前状态：{'开启' if enabled else '关闭'}",
            "开启后，新私聊用户和新群组接入都会通知管理员。",
        ]
    )


def format_runtime_status(snapshot: RuntimeSnapshot, stats: DailyStatsSummary) -> str:
    return "\n".join(
        [
            "运行状态",
            "",
            f"当前轮询：{snapshot.poll_interval_minutes} 分钟",
            f"审批提醒：{'开启' if snapshot.access_request_alerts_enabled else '关闭'}",
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
        return "当前还没有记录到任何群组，请先把 bot 拉进群。"
    lines = ["已记录群组"]
    for group in groups:
        status = "已启用" if group.is_enabled else "未启用"
        lines.append(
            f"{group.title or '未命名群组'} | chat_id={group.chat_id} | 类型={group.chat_type or '未知'} | 状态={status}"
        )
    return "\n".join(lines)


def format_enabled_private_users(users: list[RuntimeGroup]) -> str:
    if not users:
        return "当前没有已授权的私聊用户。"
    lines = ["已授权私聊用户"]
    for user in users:
        lines.append(f"{user.title or '未命名用户'} | user_id={user.chat_id} | 授权时间={format_dt(user.enabled_at)}")
    return "\n".join(lines)


def format_known_private_users(users: list[RuntimeGroup], *, admin_user_id: int) -> str:
    if not users:
        return "当前还没有记录到任何私聊用户，请先让对方私聊 bot 并发送 /start。"
    lines = ["已记录私聊用户"]
    for user in users:
        if user.chat_id == admin_user_id:
            status = "管理员"
        else:
            status = "已授权" if user.is_enabled else "未授权"
        lines.append(f"{user.title or '未命名用户'} | user_id={user.chat_id} | 状态={status}")
    return "\n".join(lines)

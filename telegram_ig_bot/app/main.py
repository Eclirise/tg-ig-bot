from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.bot.handlers import HandlerContext, build_router
from app.config import load_config
from app.db import Database
from app.downloader.gallerydl_backend import GalleryDLBackend
from app.downloader.instaloader_backend import InstaloaderBackend
from app.downloader.router import DownloaderRouter
from app.downloader.ytdlp_backend import YtDlpBackend
from app.logging_setup import install_telegram_alert_handler, setup_logging
from app.scheduler.jobs import create_scheduler
from app.services.auth_service import AccessService
from app.services.cleanup_service import CleanupService
from app.services.maintenance_service import MaintenanceService
from app.services.parse_service import ParseService
from app.services.sender_service import SenderService
from app.services.settings_service import SettingsService
from app.services.stats_service import StatsService
from app.services.subscription_service import SubscriptionService


async def main() -> None:
    config = load_config()
    setup_logging(config)
    logger = logging.getLogger(__name__)

    db = Database(config.db_path)
    db.initialize()

    access_service = AccessService(db, config)
    settings_service = SettingsService(db, config)
    cleanup_service = CleanupService()
    stats_service = StatsService(db, config)
    maintenance_service = MaintenanceService(config)
    sender_service = SenderService(cleanup_service, config)
    router = DownloaderRouter(
        [
            InstaloaderBackend(config),
            GalleryDLBackend(config),
            YtDlpBackend(config),
        ],
        temp_root=config.temp_root,
        max_concurrent_downloads=config.max_concurrent_downloads,
        rate_limit_cooldown_min_seconds=config.ig_rate_limit_cooldown_min_seconds,
        rate_limit_cooldown_max_seconds=config.ig_rate_limit_cooldown_max_seconds,
    )
    parse_service = ParseService(
        router,
        sender_service,
        stats_service,
        max_concurrent_jobs=config.max_concurrent_downloads,
    )
    subscription_service = SubscriptionService(
        db,
        settings_service,
        router,
        sender_service,
        stats_service,
        access_service,
        config,
    )

    bot = Bot(
        token=config.telegram_bot_token,
    )
    alert_service = install_telegram_alert_handler(bot, config)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="开始使用机器人"),
            BotCommand(command="commands", description="查看命令列表"),
            BotCommand(command="ig", description="也可直接发送链接解析"),
            BotCommand(command="subs", description="查看当前聊天订阅"),
            BotCommand(command="subadd", description="新增订阅"),
            BotCommand(command="submod", description="修改订阅"),
            BotCommand(command="unsubscribe", description="退订"),
            BotCommand(command="status", description="查看运行状态"),
            BotCommand(command="help", description="查看帮助"),
            BotCommand(command="chatid", description="管理员查看当前聊天 ID"),
            BotCommand(command="enable_here", description="管理员在当前群启用机器人"),
            BotCommand(command="disable_here", description="管理员在当前群停用机器人"),
            BotCommand(command="knowngroups", description="管理员查看已记录群组"),
            BotCommand(command="allowgroup", description="管理员允许指定群组"),
            BotCommand(command="denygroup", description="管理员禁止指定群组"),
            BotCommand(command="knownusers", description="管理员查看已记录私聊用户"),
            BotCommand(command="listusers", description="管理员查看已授权私聊用户"),
            BotCommand(command="allowuser", description="管理员允许指定私聊用户"),
            BotCommand(command="denyuser", description="管理员禁止指定私聊用户"),
            BotCommand(command="targetchat", description="管理员切换订阅管理目标"),
            BotCommand(command="cleartarget", description="管理员清除订阅管理目标"),
            BotCommand(command="listgroups", description="管理员查看已启用群组"),
            BotCommand(command="stats", description="管理员查看今日统计"),
            BotCommand(command="accessalerts", description="管理员切换审核通知"),
            BotCommand(command="restart", description="管理员重启机器人"),
            BotCommand(command="update_tools", description="管理员更新下载工具并自检"),
        ]
    )

    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_router(
            HandlerContext(
                config=config,
                db=db,
                access_service=access_service,
                parse_service=parse_service,
                subscription_service=subscription_service,
                settings_service=settings_service,
                stats_service=stats_service,
                maintenance_service=maintenance_service,
            )
        )
    )

    scheduler = create_scheduler(config, subscription_service, bot)
    scheduler.start()
    logger.info("telegram_ig_bot 已启动")
    alert_service.schedule_text_alert("Bot 已启动", "机器人已完成初始化并开始长轮询。", key="startup", force=True)
    try:
        await dispatcher.start_polling(bot)
    except Exception as exc:
        alert_service.schedule_text_alert("Bot 主循环退出", str(exc)[:1500], key="main-loop-crash", force=True)
        raise
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

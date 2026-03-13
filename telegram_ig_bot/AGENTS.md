# telegram_ig_bot / AGENTS

## 目标
在当前仓库内独立维护一个低资源 Telegram Instagram 机器人子项目，优先适配 Oracle Cloud E2 Micro 一类小机器。

## 运行约定
- Python 3.11+
- 启动命令：`python -m app.main`
- 测试命令：`pytest -q`
- 默认长轮询，不启用 webhook
- 临时文件发送后立即清理，不做长期缓存

## 维护约定
- 主要代码放在 `app/`
- 订阅与去重逻辑优先保持保守，不要在发送失败时提前推进 checkpoint
- 下载逻辑统一走适配器路由：Instaloader -> gallery-dl -> yt-dlp
- 群启用控制和管理员限制不要绕过
- 修改部署方式时同步更新 `README.md`、`.env.example` 和 `systemd/telegram_ig_bot.service`

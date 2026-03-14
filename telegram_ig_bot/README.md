# telegram_ig_bot

一个适合 Oracle / CentOS 7 小机器的 Telegram 解析机器人，支持 Instagram 和 YouTube 链接直发解析，也支持 Instagram 订阅轮询。

## 现在的关键能力

- 直接发送 Instagram / YouTube 链接即可解析，不再依赖 `/tg` 或 `/yt`
- 管理员会收到新私聊用户和新群接入通知，可一键允许或拒绝
- 管理员可通过 `/accessalerts` 开关审批通知
- 管理员可通过 `/restart` 让 bot 自行退出并交给 systemd 自动拉起
- 多个解析任务并发时，会提示当前解析数和排队数
- 群被移除时会自动停用并暂停轮询，避免反复报错
- 部署脚本内置 `fix-perms`，会修复权限和 SELinux context

## 常用命令

- `/ig <url>` 手动解析 Instagram 链接
- `/subs` 查看当前聊天订阅
- `/subadd <username> <feed|story|both>` 新增订阅
- `/submod <username> <only_feed|only_story|both|disable_feed|disable_story|unsubscribe>` 修改订阅
- `/unsubscribe <username>` 退订
- `/status` 查看运行状态

管理员额外命令：

- `/enable_here`
- `/disable_here`
- `/allowgroup <chat_id>`
- `/denygroup <chat_id>`
- `/allowuser <user_id>`
- `/denyuser <user_id>`
- `/targetchat <chat_id>`
- `/cleartarget`
- `/accessalerts`
- `/restart`
- `/update_tools`

## 本地运行

```bash
cd telegram_ig_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## Oracle / CentOS 7 快速部署

从拉代码开始：

```bash
sudo -i
cd /opt
git clone <YOUR_GIT_REPO_URL> tg-ig-bot
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh install
```

如果你想直接用 bootstrap：

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<branch>/bootstrap_telegram_ig_bot_centos7.sh | \
  bash -s -- --repo-url https://github.com/<owner>/<repo>.git --branch <branch> --install-dir /opt/tg-ig-bot
```

更完整的部署说明见 [DEPLOY_ORACLE.md](/d:/GithubCollection/tgigbot/tg-ig-bot/telegram_ig_bot/DEPLOY_ORACLE.md)。

## 权限 / SELinux 故障恢复

如果 systemd 在 Python 启动前报：

- `Failed to load environment files: Permission denied`
- `Failed to run 'start' task: Permission denied`

执行：

```bash
sudo -i
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh fix-perms
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh restart
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh status
```

这个修复会：

- 重新整理 `/opt/tg-ig-bot` 目录属主和可执行权限
- 对 `.env`、`app`、`.venv` 做可读/可执行修复
- 在启用 SELinux 时执行 `restorecon -RFv /opt/tg-ig-bot`
- 在 `doctor` 里附带 `ausearch -m AVC -ts recent` 诊断输出

另外，systemd unit 已不再依赖 `EnvironmentFile=`，应用会在 Python 进程内部自行读取 `.env`，因此不会再在 exec 之前被 `.env` 卡死。

## 运维命令

```bash
tg-ig-botctl status
tg-ig-botctl logs
tg-ig-botctl update
tg-ig-botctl update-tools
tg-ig-botctl fix-perms
tg-ig-botctl cleanup
tg-ig-botctl refresh-session
tg-ig-botctl doctor
```

## 测试

```bash
pytest -q
```

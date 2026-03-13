# Root Deploy Runbook

This runbook matches the current Oracle/CentOS 7 deployment where the repo lives in `/root/tg-ig-bot` and the bot runs as `root`.

## SSH In And Enter Repo

```bash
sudo -i
cd /root/tg-ig-bot/telegram_ig_bot
```

## Pull Latest Code

If you are already inside `/root/tg-ig-bot`:

```bash
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
git fetch --all --tags --prune
git checkout "$branch"
git pull --ff-only origin "$branch"
```

If you just want the common case:

```bash
cd /root/tg-ig-bot
git fetch --all --tags --prune
git checkout main
git pull --ff-only origin main
```

## Restart Or Start The Bot

```bash
cd /root/tg-ig-bot/telegram_ig_bot
bash scripts/oracle_centos7_manager.sh restart
```

If the service was never started:

```bash
cd /root/tg-ig-bot/telegram_ig_bot
bash scripts/oracle_centos7_manager.sh start
```

## Check Service Status

```bash
cd /root/tg-ig-bot/telegram_ig_bot
bash scripts/oracle_centos7_manager.sh status
```

Direct systemd check:

```bash
systemctl status telegram_ig_bot --no-pager
```

Healthy output includes:

```text
Active: active (running)
```

## Follow Logs

```bash
cd /root/tg-ig-bot/telegram_ig_bot
bash scripts/oracle_centos7_manager.sh logs
```

Or inspect recent systemd logs once:

```bash
journalctl -u telegram_ig_bot -n 80 --no-pager
```

## Full Update Flow

Use this after the local script fix is present on the server:

```bash
sudo -i
cd /root/tg-ig-bot/telegram_ig_bot
bash scripts/oracle_centos7_manager.sh update
```

That command pulls code, refreshes dependencies, compiles the app, restarts the service, cleans caches, and prints status.

## Common Daily Commands

```bash
sudo -i
cd /root/tg-ig-bot/telegram_ig_bot

bash scripts/oracle_centos7_manager.sh status
bash scripts/oracle_centos7_manager.sh logs
bash scripts/oracle_centos7_manager.sh restart
bash scripts/oracle_centos7_manager.sh doctor
```

If `/usr/local/bin/tg-ig-botctl` exists, these are equivalent:

```bash
sudo -i
tg-ig-botctl status
tg-ig-botctl logs
tg-ig-botctl restart
tg-ig-botctl update
```

## If Update Fails On Old Git

CentOS 7 may ship a git that breaks on `git -C`. Use the manual pull flow instead:

```bash
sudo -i
cd /root/tg-ig-bot
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
git fetch --all --tags --prune
git checkout "$branch"
git pull --ff-only origin "$branch"
cd /root/tg-ig-bot/telegram_ig_bot
bash scripts/oracle_centos7_manager.sh restart
bash scripts/oracle_centos7_manager.sh status
```

## Quick Functional Check In Telegram

1. Open a private chat with the bot.
2. Send `/start`.
3. Send `/chatid` or `/stats`.
4. Send `/ig <instagram_url>` or `/tg <instagram_url>`.

If the bot replies and logs stay clean, the deployment is healthy.
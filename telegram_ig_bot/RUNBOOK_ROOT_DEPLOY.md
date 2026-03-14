# Root Deploy Runbook

适用于你已经 `sudo -i`，并且代码位于 `/opt/tg-ig-bot` 的情况。

## 更新代码

```bash
cd /opt/tg-ig-bot
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
git fetch --all --tags --prune
git checkout "$branch"
git pull --ff-only origin "$branch"
```

## 重启服务

```bash
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh restart
```

## 查看状态

```bash
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh status
```

## 看日志

```bash
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh logs
```

## 一键更新

```bash
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh update
```

## 修复权限 / SELinux

```bash
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh fix-perms
```

需要看最近 SELinux AVC 的话：

```bash
ausearch -m AVC -ts recent
```

## 日常检查

```bash
tg-ig-botctl status
tg-ig-botctl logs
tg-ig-botctl doctor
tg-ig-botctl fix-perms
```

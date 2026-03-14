# Oracle / Linux 部署指南

这份文档默认安装到 `/opt/tg-ig-bot`，脚本已适配 Oracle Linux、CentOS Stream、Rocky、Alma、RHEL、Debian、Ubuntu。

说明：脚本文件名仍保留 `oracle_centos7_manager.sh` / `bootstrap_telegram_ig_bot_centos7.sh`，只是为了兼容旧用法。

## 1. 从拉代码开始部署

```bash
sudo -i
cd /opt
git clone <YOUR_GIT_REPO_URL> tg-ig-bot
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh install
```

脚本会自动完成：

- 在 CentOS 7 时切换 vault 源
- 编译 OpenSSL 3.0 / Python 3.11
- 建立虚拟环境并安装依赖
- 交互写入 `.env`
- 生成 systemd / watchdog 单元
- 修复 `/opt/tg-ig-bot` 权限和 SELinux context
- 启动服务并写入 `tg-ig-botctl`

## 2. 无交互 bootstrap

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<branch>/bootstrap_telegram_ig_bot_centos7.sh | \
  bash -s -- --repo-url https://github.com/<owner>/<repo>.git --branch <branch> --install-dir /opt/tg-ig-bot
```

## 3. 初次在 Telegram 里操作

1. 私聊 bot 并发送 `/start`
2. 管理员自己的私聊天然可用
3. 别人首次私聊你，管理员会收到审批通知
4. 把 bot 拉进群后，管理员也会收到群接入通知
5. 管理员允许后，用户或群就可以直接发送链接解析

## 4. 常用运维命令

```bash
sudo -i
tg-ig-botctl status
tg-ig-botctl logs
tg-ig-botctl update
tg-ig-botctl update-tools
tg-ig-botctl fix-perms
tg-ig-botctl doctor
```

## 5. 处理 systemd Permission denied

如果看到：

```text
Failed to load environment files: Permission denied
Failed to run 'start' task: Permission denied
```

执行：

```bash
sudo -i
cd /opt/tg-ig-bot
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh fix-perms
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh restart
bash telegram_ig_bot/scripts/oracle_centos7_manager.sh status
```

如果 SELinux 开启，`fix-perms` 会自动执行：

```bash
restorecon -RFv /opt/tg-ig-bot
```

如需继续排 SELinux 拒绝：

```bash
ausearch -m AVC -ts recent
```

## 6. 为什么这次不会再卡在 .env

新的 unit 不再使用 `EnvironmentFile=`。  
`.env` 由 Python 进程在应用内部读取，所以 systemd 不会在 exec 前因为 `.env` 权限或 SELinux 标签错误直接失败。

这意味着：

- systemd 启动阶段更稳
- `fix-perms` 能在需要时修目录权限和 context
- bot 自身可通过 `/restart` 自恢复

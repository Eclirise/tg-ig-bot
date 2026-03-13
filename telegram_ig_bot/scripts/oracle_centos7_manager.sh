#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'"'"'\n\t'"'"'

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/.." && pwd)"
INSTALL_DIR="$REPO_ROOT"
RUNTIME_DIR="$INSTALL_DIR/.runtime"
BUILD_DIR="$INSTALL_DIR/.build"
VENV_DIR="$APP_DIR/.venv"
ENV_FILE="$APP_DIR/.env"
SERVICE_NAME="telegram_ig_bot"
WATCHDOG_NAME="telegram_ig_bot-watchdog"
ALERT_TEMPLATE_NAME="telegram_ig_bot-alert@"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
WATCHDOG_SERVICE_FILE="/etc/systemd/system/${WATCHDOG_NAME}.service"
WATCHDOG_TIMER_FILE="/etc/systemd/system/${WATCHDOG_NAME}.timer"
ALERT_TEMPLATE_FILE="/etc/systemd/system/${ALERT_TEMPLATE_NAME}.service"
SYMLINK_PATH="/usr/local/bin/tg-ig-botctl"
RUN_USER="${SUDO_USER:-${USER:-root}}"
RUN_GROUP="$RUN_USER"
REPO_URL_OVERRIDE=""
BRANCH_OVERRIDE=""
REMAINING_ARGS=()

if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

log() { echo "[tg-ig-bot] $*"; }
warn() { echo "[tg-ig-bot][WARN] $*" >&2; }
die() { echo "[tg-ig-bot][ERROR] $*" >&2; exit 1; }
run() { log "$*"; "$@"; }
run_root() {
  if [[ -n "$SUDO" ]]; then
    log "$SUDO $*"
    $SUDO "$@"
  else
    log "$*"
    "$@"
  fi
}
run_as_user() {
  local target_user="$1"
  shift
  if command -v sudo >/dev/null 2>&1; then
    log "sudo -u $target_user $*"
    sudo -u "$target_user" "$@"
  else
    local quoted
    quoted=$(printf ' %q' "$@")
    run_root su -s /bin/bash - "$target_user" -c "${quoted# }"
  fi
}

validate_install_location() {
  if [[ "$INSTALL_DIR" == /root/* && "$RUN_USER" != "root" ]]; then
    if [[ "$(id -u)" -eq 0 ]]; then
      warn "安装目录 $INSTALL_DIR 位于 /root 下，检测到继承的运行用户是 $RUN_USER。将改用 root 继续安装。"
      RUN_USER="root"
      RUN_GROUP="root"
      return
    fi
    die "安装目录 $INSTALL_DIR 位于 /root 下，但运行用户是 $RUN_USER。普通用户无法穿过 /root 创建虚拟环境。请改用 /opt/tg-ig-bot 或 /home/$RUN_USER/tg-ig-bot。"
  fi
}

usage() {
  cat <<EOF
用法：bash scripts/oracle_centos7_manager.sh <命令>

命令：
  install           首次安装或修复安装
  configure         重新写入 .env 配置
  refresh-session   重新生成 Instagram session
  update            拉取最新代码并重装依赖
  update-tools      仅更新 Instaloader / gallery-dl / yt-dlp 并自检
  restart           重启服务
  start             启动服务
  stop              停止服务
  status            查看服务状态
  logs              查看最近日志并持续跟随
  cleanup           清理缓存、旧临时文件和无用构建目录
  doctor            输出环境体检信息
  uninstall         卸载 bot、systemd 单元和安装目录
  internal-alert    systemd 内部调用：发送 Telegram 告警
  internal-watchdog systemd 内部调用：巡检服务与磁盘
  menu              打开交互菜单
EOF
}

parse_common_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo-url)
        REPO_URL_OVERRIDE="$2"
        shift 2
        ;;
      --branch)
        BRANCH_OVERRIDE="$2"
        shift 2
        ;;
      *)
        break
        ;;
    esac
  done
  REMAINING_ARGS=("$@")
}

ensure_centos7() {
  [[ -f /etc/centos-release ]] || die "当前系统不是 CentOS 7，脚本按 CentOS 7 编写。"
  grep -q 'release 7' /etc/centos-release || die "当前系统不是 CentOS 7。"
}

configure_centos7_vault_repos() {
  ensure_centos7
  local marker="/etc/yum.repos.d/CentOS-Vault-7.9.2009.repo"
  if [[ -f "$marker" ]]; then
    return
  fi
  warn "CentOS 7 已结束维护，脚本会切换到 vault 源。"
  run_root mkdir -p /etc/yum.repos.d/backup-centos7-vault
  run_root bash -lc 'shopt -s nullglob; for file in /etc/yum.repos.d/*.repo; do mv "$file" /etc/yum.repos.d/backup-centos7-vault/; done'
  run_root bash -lc "cat > '$marker' <<'EOF'
[base]
name=CentOS-7.9.2009 - Base
baseurl=http://vault.centos.org/7.9.2009/os/\$basearch/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7

[updates]
name=CentOS-7.9.2009 - Updates
baseurl=http://vault.centos.org/7.9.2009/updates/\$basearch/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7

[extras]
name=CentOS-7.9.2009 - Extras
baseurl=http://vault.centos.org/7.9.2009/extras/\$basearch/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7

[centos-sclo-rh]
name=CentOS-7.9.2009 - SCLo rh
baseurl=http://vault.centos.org/7.9.2009/sclo/\$basearch/rh/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7

[centos-sclo-sclo]
name=CentOS-7.9.2009 - SCLo sclo
baseurl=http://vault.centos.org/7.9.2009/sclo/\$basearch/sclo/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
EOF"
  run_root yum clean all
  run_root yum makecache -y
}

install_system_packages() {
  configure_centos7_vault_repos
  run_root yum install -y git curl wget tar xz make which findutils ca-certificates bzip2 patch perl perl-IPC-Cmd
  run_root yum install -y gcc gcc-c++ zlib-devel bzip2-devel readline-devel sqlite-devel libffi-devel xz-devel ncurses-devel gdbm-devel tk-devel libuuid-devel openssl-devel
  run_root yum install -y firewalld || true
  run_root yum install -y centos-release-scl-rh centos-release-scl || true
  if ! run_root yum install -y devtoolset-11-gcc devtoolset-11-gcc-c++ devtoolset-11-binutils; then
    run_root yum install -y devtoolset-10-gcc devtoolset-10-gcc-c++ devtoolset-10-binutils
  fi
}

configure_firewall() {
  if ! command -v firewall-cmd >/dev/null 2>&1; then
    warn "???? firewalld??????????"
    return
  fi
  run_root systemctl enable firewalld >/dev/null 2>&1 || true
  run_root systemctl start firewalld >/dev/null 2>&1 || true
  run_root firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1 || true
  run_root firewall-cmd --reload >/dev/null 2>&1 || true
  log "??????????? SSH??? bot ??????????????????"
}

enable_devtoolset() {
  if [[ -f /opt/rh/devtoolset-11/enable ]]; then
    # shellcheck disable=SC1091
    source /opt/rh/devtoolset-11/enable
    return
  fi
  if [[ -f /opt/rh/devtoolset-10/enable ]]; then
    # shellcheck disable=SC1091
    source /opt/rh/devtoolset-10/enable
    return
  fi
  die "没有找到可用的 devtoolset，请先检查 yum 源。"
}

fetch_latest_python_311_version() {
  local version
  version="$(curl -fsSL https://www.python.org/ftp/python/ | grep -o '3\.11\.[0-9]\+/' | tr -d '/' | sort -V | tail -n1 || true)"
  echo "${version:-3.11.15}"
}

fetch_latest_openssl_30_version() {
  local version
  version="$(curl -fsSL https://www.openssl.org/source/ | grep -o 'openssl-3\.0\.[0-9]\+\.tar\.gz' | sed 's/^openssl-//; s/\.tar\.gz$//' | sort -V | tail -n1 || true)"
  echo "${version:-3.0.18}"
}

build_runtime() {
  install_system_packages
  enable_devtoolset
  run mkdir -p "$BUILD_DIR" "$RUNTIME_DIR"

  local openssl_version python_version openssl_prefix python_prefix
  openssl_version="$(fetch_latest_openssl_30_version)"
  python_version="$(fetch_latest_python_311_version)"
  openssl_prefix="$RUNTIME_DIR/openssl-3.0"
  python_prefix="$RUNTIME_DIR/python-3.11"

  if [[ ! -x "$openssl_prefix/bin/openssl" || "$("$openssl_prefix/bin/openssl" version 2>/dev/null | awk '{print $2}')" != "$openssl_version" ]]; then
    log "编译 OpenSSL ${openssl_version}"
    rm -rf "$BUILD_DIR/openssl-$openssl_version" "$BUILD_DIR/openssl-$openssl_version.tar.gz"
    run_root bash -lc "cd '$BUILD_DIR' && curl -fsSLO 'https://www.openssl.org/source/openssl-${openssl_version}.tar.gz' && tar -xzf 'openssl-${openssl_version}.tar.gz'"
    run_root bash -lc "source /opt/rh/devtoolset-11/enable 2>/dev/null || source /opt/rh/devtoolset-10/enable 2>/dev/null || true; cd '$BUILD_DIR/openssl-${openssl_version}' && ./Configure --prefix='$openssl_prefix' --openssldir='$openssl_prefix/ssl' linux-x86_64 shared zlib && make -j1 && make install_sw"
  fi

  [[ -x "$openssl_prefix/bin/openssl" ]] || die "OpenSSL 构建失败：缺少 $openssl_prefix/bin/openssl"
  "$openssl_prefix/bin/openssl" version >/dev/null 2>&1 || die "OpenSSL 构建失败：openssl 可执行文件无法运行"
  [[ -f "$openssl_prefix/include/openssl/ssl.h" ]] || die "OpenSSL 构建失败：缺少 ssl.h 头文件"
  compgen -G "$openssl_prefix/lib*/libssl*" >/dev/null || die "OpenSSL 构建失败：缺少 libssl 库文件"

  local rebuild_python=0
  if [[ ! -x "$python_prefix/bin/python3.11" || "$("$python_prefix/bin/python3.11" -V 2>&1 | awk '{print $2}')" != "$python_version" ]]; then
    rebuild_python=1
  elif ! "$python_prefix/bin/python3.11" - <<'PY' >/dev/null 2>&1
import ssl
print(ssl.OPENSSL_VERSION)
PY
  then
    warn "检测到现有 Python 缺少 ssl 模块，准备强制重编译。"
    rebuild_python=1
  fi

  if [[ "$rebuild_python" -eq 1 ]]; then
    log "编译 Python ${python_version}"
    rm -rf "$python_prefix"
    rm -rf "$BUILD_DIR/Python-$python_version" "$BUILD_DIR/Python-$python_version.tgz"
    run_root bash -lc "cd '$BUILD_DIR' && curl -fsSLO 'https://www.python.org/ftp/python/${python_version}/Python-${python_version}.tgz' && tar -xzf 'Python-${python_version}.tgz'"
    run_root bash -lc "source /opt/rh/devtoolset-11/enable 2>/dev/null || source /opt/rh/devtoolset-10/enable 2>/dev/null || true; cd '$BUILD_DIR/Python-${python_version}' && CPPFLAGS='-I${openssl_prefix}/include' LDFLAGS='-L${openssl_prefix}/lib' ./configure --prefix='$python_prefix' --with-openssl='$openssl_prefix' --with-openssl-rpath=auto --with-ensurepip=install && make -j1 && make install"
  fi

  python_supports_ssl "$python_prefix/bin/python3.11" || die "Python 构建失败：ssl 模块不可用，请检查 $BUILD_DIR/Python-${python_version} 下的 configure 输出与 Modules/_ssl 构建日志"
}

python_bin() { echo "$RUNTIME_DIR/python-3.11/bin/python3.11"; }
venv_python_bin() { echo "$VENV_DIR/bin/python"; }
venv_pip_bin() { echo "$VENV_DIR/bin/pip"; }

python_supports_ssl() {
  local python_exe="$1"
  [[ -x "$python_exe" ]] || return 1
  "$python_exe" - <<'PY' >/dev/null 2>&1
import ssl
print(ssl.OPENSSL_VERSION)
PY
}

venv_is_healthy() {
  [[ -x "$(venv_python_bin)" ]] || return 1
  [[ -x "$(venv_pip_bin)" ]] || return 1
  python_supports_ssl "$(venv_python_bin)" || return 1
  "$(venv_pip_bin)" --version >/dev/null 2>&1
}

ensure_python_runtime() {
  if [[ ! -x "$(python_bin)" ]] || ! python_supports_ssl "$(python_bin)"; then
    build_runtime
  fi
}

shrink_runtime_footprint() {
  local py_lib="$RUNTIME_DIR/python-3.11/lib/python3.11"
  if [[ -d "$py_lib" ]]; then
    run_root rm -rf "$py_lib/test" "$py_lib/idlelib" "$py_lib/tkinter" "$py_lib/turtledemo" 2>/dev/null || true
  fi
  run_root find "$RUNTIME_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  run_root find "$RUNTIME_DIR" -type f -name '*.a' -delete 2>/dev/null || true
}

install_python_dependencies() {
  ensure_python_runtime
  if [[ -d "$VENV_DIR" ]] && ! venv_is_healthy; then
    warn "检测到现有虚拟环境异常，准备重建。"
    run_root rm -rf "$VENV_DIR"
  fi
  if [[ ! -d "$VENV_DIR" ]]; then
    if [[ "$(id -u)" -eq 0 && "$RUN_USER" != "root" ]]; then
      run_as_user "$RUN_USER" "$(python_bin)" -m venv "$VENV_DIR"
    else
      run "$(python_bin)" -m venv "$VENV_DIR"
    fi
  fi
  if [[ "$(id -u)" -eq 0 && "$RUN_USER" != "root" ]]; then
    run_as_user "$RUN_USER" "$(venv_pip_bin)" install --no-cache-dir --upgrade pip setuptools wheel
    run_as_user "$RUN_USER" "$(venv_pip_bin)" install --no-cache-dir --upgrade -r "$APP_DIR/requirements.txt"
  else
    run "$(venv_pip_bin)" install --no-cache-dir --upgrade pip setuptools wheel
    run "$(venv_pip_bin)" install --no-cache-dir --upgrade -r "$APP_DIR/requirements.txt"
  fi
  shrink_runtime_footprint
}

show_downloader_tool_versions() {
  local instaloader_version="missing"
  local gallery_dl_version="missing"
  local yt_dlp_version="missing"

  if [[ -x "$VENV_DIR/bin/instaloader" ]]; then
    instaloader_version="$($VENV_DIR/bin/instaloader --version 2>/dev/null | head -n 1 || echo unknown)"
  fi
  if [[ -x "$VENV_DIR/bin/gallery-dl" ]]; then
    gallery_dl_version="$($VENV_DIR/bin/gallery-dl --version 2>/dev/null | head -n 1 || echo unknown)"
  fi
  if [[ -x "$VENV_DIR/bin/yt-dlp" ]]; then
    yt_dlp_version="$($VENV_DIR/bin/yt-dlp --version 2>/dev/null | head -n 1 || echo unknown)"
  fi

  echo "Instaloader：$instaloader_version"
  echo "gallery-dl：$gallery_dl_version"
  echo "yt-dlp：$yt_dlp_version"
}

verify_downloader_tools() {
  local failed=0

  if [[ ! -x "$VENV_DIR/bin/instaloader" ]] || ! "$VENV_DIR/bin/instaloader" --version >/dev/null 2>&1; then
    warn "Instaloader 自检失败"
    failed=1
  fi
  if [[ ! -x "$VENV_DIR/bin/gallery-dl" ]] || ! "$VENV_DIR/bin/gallery-dl" --version >/dev/null 2>&1; then
    warn "gallery-dl 自检失败"
    failed=1
  fi
  if [[ ! -x "$VENV_DIR/bin/yt-dlp" ]] || ! "$VENV_DIR/bin/yt-dlp" --version >/dev/null 2>&1; then
    warn "yt-dlp 自检失败"
    failed=1
  fi
  if [[ -x "$VENV_DIR/bin/pip" ]] && ! "$VENV_DIR/bin/pip" check >/dev/null 2>&1; then
    warn "pip check 失败"
    failed=1
  fi

  return "$failed"
}

prompt_value() {
  local prompt="$1"
  local default_value="${2:-}"
  local result
  if [[ -n "$default_value" ]]; then
    read -r -p "$prompt [$default_value]: " result || true
    echo "${result:-$default_value}"
  else
    read -r -p "$prompt: " result || true
    echo "$result"
  fi
}

prompt_secret() {
  local prompt="$1"
  local result
  read -r -s -p "$prompt: " result || true
  echo
  echo "$result"
}

verify_bot_token() {
  local token="$1"
  "$(python_bin)" - "$token" <<'PY'
import json
import sys
import urllib.request

token = sys.argv[1]
url = f"https://api.telegram.org/bot{token}/getMe"
try:
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.load(response)
except Exception as exc:
    print(f"ERROR::{exc}")
    raise SystemExit(1)
if not payload.get("ok"):
    print(f"ERROR::{payload}")
    raise SystemExit(1)
print((payload.get("result") or {}).get("username", ""))
PY
}

auto_detect_admin_id() {
  local token="$1"
  "$(python_bin)" - "$token" <<'PY'
import json
import sys
import urllib.request

token = sys.argv[1]
url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.load(response)
except Exception:
    raise SystemExit(0)
if not payload.get("ok"):
    raise SystemExit(0)
seen = {}
for item in payload.get("result") or []:
    msg = item.get("message") or item.get("edited_message") or item.get("my_chat_member") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":
        continue
    from_user = msg.get("from") or {}
    uid = chat.get("id")
    if uid is None:
        continue
    label = chat.get("username") or " ".join(part for part in [from_user.get("first_name"), from_user.get("last_name")] if part) or str(uid)
    seen[str(uid)] = label
for idx, (uid, label) in enumerate(seen.items(), start=1):
    print(f"{idx}|{uid}|{label}")
PY
}

write_env_file() {
  local bot_token="$1"
  local admin_id="$2"
  local ig_username="$3"
  local poll_interval="$4"
  local session_file="$APP_DIR/data/instagram.session"
  local cookies_file="$APP_DIR/data/instagram.cookies.txt"
  mkdir -p "$APP_DIR/data" "$APP_DIR/logs" "$APP_DIR/data/tmp"
  cat > "$ENV_FILE" <<EOF
TELEGRAM_BOT_TOKEN=$bot_token
ADMIN_TG_USER_ID=$admin_id
APP_TIMEZONE=Asia/Shanghai

DATA_DIR=$APP_DIR/data
LOGS_DIR=$APP_DIR/logs
TEMP_ROOT=$APP_DIR/data/tmp
SQLITE_PATH=$APP_DIR/data/telegram_ig_bot.sqlite3

INSTAGRAM_USERNAME=$ig_username
INSTAGRAM_SESSION_FILE=$session_file
INSTAGRAM_COOKIES_FILE=$cookies_file

INSTALOADER_BINARY=$VENV_DIR/bin/instaloader
GALLERY_DL_BINARY=$VENV_DIR/bin/gallery-dl
YT_DLP_BINARY=$VENV_DIR/bin/yt-dlp

LOG_LEVEL=INFO
LOG_MAX_BYTES=262144
LOG_BACKUP_COUNT=2
LOG_TO_STDOUT=false
DOWNLOAD_TIMEOUT_SECONDS=240
MAX_CONCURRENT_DOWNLOADS=1
SCHEDULER_TICK_SECONDS=60
DEFAULT_POLL_INTERVAL_MINUTES=$poll_interval
CLEANUP_AFTER_SEND=true
CLEANUP_ON_FAILURE=true
POLL_BATCH_SIZE=3
POLL_DUE_LIMIT=10
TELEGRAM_ALERTS_ENABLED=true
TELEGRAM_ALERT_MIN_INTERVAL_SECONDS=900
RATE_LIMIT_BACKOFF_MINUTES=30
RATE_LIMIT_BACKOFF_MAX_MINUTES=120
IG_RATE_LIMIT_COOLDOWN_MIN_SECONDS=90
IG_RATE_LIMIT_COOLDOWN_MAX_SECONDS=240
EOF
  chmod 600 "$ENV_FILE"
}

load_env_file() {
  [[ -f "$ENV_FILE" ]] || die "没有找到 $ENV_FILE，请先执行 install 或 configure。"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

configure_env_interactive() {
  ensure_python_runtime
  local existing_token="" existing_admin="" existing_ig="" existing_poll="10"
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    existing_token="${TELEGRAM_BOT_TOKEN:-}"
    existing_admin="${ADMIN_TG_USER_ID:-}"
    existing_ig="${INSTAGRAM_USERNAME:-}"
    existing_poll="${DEFAULT_POLL_INTERVAL_MINUTES:-10}"
  fi

  local repo_origin
  repo_origin="$(git -C "$INSTALL_DIR" config --get remote.origin.url 2>/dev/null || true)"
  [[ -n "$repo_origin" ]] && log "当前仓库来源：$repo_origin"

  local bot_token bot_username admin_id="" ig_username poll_interval detected_lines choice selected_line
  while true; do
    bot_token="$(prompt_secret '请输入 Telegram Bot Token')"
    bot_token="${bot_token:-$existing_token}"
    [[ -n "$bot_token" ]] || { warn 'Bot Token 不能为空'; continue; }
    if bot_username="$(verify_bot_token "$bot_token" 2>/dev/null)"; then
      log "Bot Token 有效，机器人用户名：@$bot_username"
      break
    fi
    warn "Token 校验失败，请重新输入。"
  done

  echo
  echo "现在请在 Telegram 里搜索 @$bot_username，先私聊它并发送 /start。"
  read -r -p '发送完成后按回车继续自动识别管理员 ID，或者输入 skip 手动填写: ' choice || true
  if [[ "$choice" != "skip" ]]; then
    detected_lines="$(auto_detect_admin_id "$bot_token")"
    if [[ -n "$detected_lines" ]]; then
      echo "检测到以下私聊用户："
      echo "$detected_lines" | awk -F'|' '{printf "  [%s] %s (%s)\n", $1, $3, $2}'
      choice="$(prompt_value '请选择管理员编号，或直接输入 Telegram 数字 ID' "$existing_admin")"
      if [[ "$choice" =~ ^[0-9]+$ ]]; then
        selected_line="$(echo "$detected_lines" | awk -F'|' -v idx="$choice" '$1 == idx {print $2}')"
        admin_id="${selected_line:-$choice}"
      fi
    fi
  fi
  if [[ -z "$admin_id" ]]; then
    admin_id="$(prompt_value '请输入管理员 Telegram 数字 ID' "$existing_admin")"
  fi
  [[ "$admin_id" =~ ^-?[0-9]+$ ]] || die '管理员 Telegram ID 必须是数字。'

  ig_username="$(prompt_value '如果要启用 Story / 私密内容，请输入 Instagram 用户名（可留空）' "$existing_ig")"
  poll_interval="$(prompt_value '默认轮询频率，只能填 5 或 10' "$existing_poll")"
  [[ "$poll_interval" == "5" || "$poll_interval" == "10" ]] || poll_interval="10"

  write_env_file "$bot_token" "$admin_id" "$ig_username" "$poll_interval"
  run_root chown -R "$RUN_USER:$RUN_GROUP" "$APP_DIR"
  log "已写入配置：$ENV_FILE"
}

refresh_instagram_session() {
  load_env_file
  [[ -n "${INSTAGRAM_USERNAME:-}" ]] || die "INSTAGRAM_USERNAME 为空，请先执行 configure。"
  log "将使用账号 ${INSTAGRAM_USERNAME} 重新生成 session。可能会要求输入密码/验证码。"
  run_root mkdir -p "$APP_DIR/data"
  run_root chown -R "$RUN_USER:$RUN_GROUP" "$APP_DIR/data"
  run_as_user "$RUN_USER" "$VENV_DIR/bin/instaloader" --login "$INSTAGRAM_USERNAME" --sessionfile "$APP_DIR/data/instagram.session"
  log "Instagram session 已刷新：$APP_DIR/data/instagram.session"
}

write_systemd_units() {
  local run_user="${1:-$RUN_USER}"
  local run_group="${2:-$RUN_GROUP}"

  run_root bash -lc "cat > '$SERVICE_FILE' <<EOF
[Unit]
Description=telegram_ig_bot
After=network-online.target
Wants=network-online.target
OnFailure=${ALERT_TEMPLATE_NAME}%n.service

[Service]
Type=simple
User=$run_user
Group=$run_group
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/python -m app.main
Restart=always
RestartSec=20
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
ReadWritePaths=$APP_DIR
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF"

  run_root bash -lc "cat > '$ALERT_TEMPLATE_FILE' <<EOF
[Unit]
Description=telegram_ig_bot alert for %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash -lc '/usr/local/bin/tg-ig-botctl internal-alert "systemd 服务异常" "服务 %i 在 $(hostname) 上异常退出，请执行 tg-ig-botctl status 和 tg-ig-botctl logs 排查。"'
EOF"

  run_root bash -lc "cat > '$WATCHDOG_SERVICE_FILE' <<EOF
[Unit]
Description=telegram_ig_bot watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=$APP_DIR
ExecStart=/usr/local/bin/tg-ig-botctl internal-watchdog
EOF"

  run_root bash -lc "cat > '$WATCHDOG_TIMER_FILE' <<EOF
[Unit]
Description=telegram_ig_bot watchdog timer

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true
Unit=${WATCHDOG_NAME}.service

[Install]
WantedBy=timers.target
EOF"

  run_root ln -sf "$SCRIPT_PATH" "$SYMLINK_PATH"
  run_root systemctl daemon-reload
}

start_service() {
  run_root systemctl enable "$SERVICE_NAME"
  run_root systemctl enable "${WATCHDOG_NAME}.timer"
  run_root systemctl restart "$SERVICE_NAME"
  run_root systemctl restart "${WATCHDOG_NAME}.timer"
}
stop_service() { run_root systemctl stop "$SERVICE_NAME" || true; }
restart_service() { run_root systemctl restart "$SERVICE_NAME"; }

show_status() {
  run_root systemctl status "$SERVICE_NAME" --no-pager || true
  echo
  doctor
}

show_logs() {
  if [[ -f "$APP_DIR/logs/telegram_ig_bot.log" ]]; then
    tail -n 200 -F "$APP_DIR/logs/telegram_ig_bot.log"
    return
  fi
  run_root journalctl -u "$SERVICE_NAME" -n 100 -f
}

cleanup_cache() {
  log "清理临时目录、旧构建目录和无用缓存"
  run_root bash -lc "mkdir -p '$APP_DIR/data/tmp' '$APP_DIR/logs'"
  run_root find "$APP_DIR/data/tmp" -mindepth 1 -maxdepth 1 -mmin +180 -exec rm -rf {} + 2>/dev/null || true
  run_root find "$INSTALL_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  run_root rm -rf "$BUILD_DIR" "$APP_DIR/.pytest_tmp" 2>/dev/null || true
  run_root bash -lc 'shopt -s nullglob; rm -rf "$1"/.pytest_tmp_run_*' -- "$APP_DIR" 2>/dev/null || true
  if [[ -x "$VENV_DIR/bin/pip" ]]; then
    "$VENV_DIR/bin/pip" cache purge >/dev/null 2>&1 || true
  fi
  if [[ -f "$APP_DIR/logs/telegram_ig_bot.log" ]]; then
    local size_kb
    size_kb="$(du -k "$APP_DIR/logs/telegram_ig_bot.log" | awk '{print $1}')"
    if [[ "$size_kb" -gt 512 ]]; then
      tail -n 500 "$APP_DIR/logs/telegram_ig_bot.log" > "$APP_DIR/logs/telegram_ig_bot.log.trimmed"
      mv "$APP_DIR/logs/telegram_ig_bot.log.trimmed" "$APP_DIR/logs/telegram_ig_bot.log"
    fi
  fi
  run_root journalctl --vacuum-size=20M >/dev/null 2>&1 || true
  run_root yum clean all >/dev/null 2>&1 || true
}

send_alert_message() {
  load_env_file
  local message="$1"
  local key="${2:-manual}"
  local cooldown="${3:-900}"
  local state_dir="$APP_DIR/data/runtime-alerts"
  local stamp_file="$state_dir/${key}.stamp"
  local now old="0"
  run_root mkdir -p "$state_dir"
  now="$(date +%s)"
  [[ -f "$stamp_file" ]] && old="$(cat "$stamp_file" 2>/dev/null || echo 0)"
  if (( now - old < cooldown )); then
    return 0
  fi
  echo "$now" > "$stamp_file"
  curl -fsS --max-time 20 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${ADMIN_TG_USER_ID}" \
    --data-urlencode "text=${message}" >/dev/null || true
}

internal_alert() {
  local title="${REMAINING_ARGS[0]:-telegram_ig_bot 提醒}"
  local detail="${REMAINING_ARGS[1]:-有新的系统告警，请登录服务器检查。}"
  send_alert_message "【${title}】
主机：$(hostname)

${detail}" "systemd_$(echo "$title" | tr ' ' '_')" 900
}

internal_watchdog() {
  load_env_file
  local free_mb tmp_mb
  free_mb="$(df -Pm "$INSTALL_DIR" | awk 'NR==2{print $4}')"
  tmp_mb="$(du -sm "$APP_DIR/data/tmp" 2>/dev/null | awk '{print $1}')"
  [[ -n "$tmp_mb" ]] || tmp_mb="0"

  if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    send_alert_message "【Bot 巡检告警】
主机：$(hostname)

检测到 ${SERVICE_NAME} 未运行，已经尝试自动重启。" "watchdog_service_down" 900
    systemctl restart "$SERVICE_NAME" || true
  fi

  if [[ "$free_mb" -lt 512 ]]; then
    cleanup_cache
    send_alert_message "【磁盘空间告警】
主机：$(hostname)

当前剩余磁盘仅 ${free_mb}MB，已执行一次自动清理。" "watchdog_disk_low" 21600
  fi

  if [[ "$tmp_mb" -gt 512 ]]; then
    cleanup_cache
    send_alert_message "【临时目录偏大】
主机：$(hostname)

临时目录约 ${tmp_mb}MB，已尝试清理。" "watchdog_tmp_large" 21600
  fi
}

update_code() {
  local branch
  branch="$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  run_as_user "$RUN_USER" git -C "$INSTALL_DIR" fetch --all --tags --prune
  run_as_user "$RUN_USER" git -C "$INSTALL_DIR" checkout "$branch"
  run_as_user "$RUN_USER" git -C "$INSTALL_DIR" pull --ff-only origin "$branch"
  install_python_dependencies
  run "$(venv_python_bin)" -m compileall "$APP_DIR/app"
  restart_service
  cleanup_cache
  show_status
}

update_downloader_tools() {
  install_python_dependencies
  if [[ "$(id -u)" -eq 0 && "$RUN_USER" != "root" ]]; then
    run_as_user "$RUN_USER" "$(venv_python_bin)" -m compileall "$APP_DIR/app"
  else
    run "$(venv_python_bin)" -m compileall "$APP_DIR/app"
  fi
  verify_downloader_tools || die "下载工具更新后自检失败，请查看上面的输出。"
  echo
  echo "下载工具更新完成，当前版本："
  show_downloader_tool_versions
  echo
  echo "建议随后执行一次 tg-ig-botctl restart，让 Instaloader 模块立即加载新版本。"
}

doctor() {
  echo "安装目录：$INSTALL_DIR"
  echo "应用目录：$APP_DIR"
  echo "虚拟环境：$VENV_DIR"
  echo "配置文件：$ENV_FILE"
  echo "运行用户：$RUN_USER"
  echo "磁盘剩余：$(df -h "$INSTALL_DIR" | awk 'NR==2{print $4}')"
  if [[ -f "$ENV_FILE" ]]; then
    load_env_file
    echo "管理员 TG：$ADMIN_TG_USER_ID"
    echo "默认轮询：${DEFAULT_POLL_INTERVAL_MINUTES:-unknown} 分钟"
    echo "日志文件：$APP_DIR/logs/telegram_ig_bot.log"
  fi
  [[ -x "$(python_bin)" ]] && echo "Python：$("$(python_bin)" -V 2>&1)"
  [[ -x "$VENV_DIR/bin/pip" ]] && echo "aiogram：$($VENV_DIR/bin/pip show aiogram 2>/dev/null | awk '/Version:/{print $2}')"
  show_downloader_tool_versions
  echo "systemd：$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo unknown)"
}

install_or_repair() {
  validate_install_location
  build_runtime
  configure_firewall
  install_python_dependencies
  configure_env_interactive
  write_systemd_units "$RUN_USER" "$RUN_GROUP"
  run_root chown -R "$RUN_USER:$RUN_GROUP" "$INSTALL_DIR"
  if [[ -f "$ENV_FILE" ]]; then
    load_env_file
    if [[ -n "${INSTAGRAM_USERNAME:-}" ]]; then
      local refresh_choice
      refresh_choice="$(prompt_value '是否现在生成/刷新 Instagram session？填 yes 或 no' 'no')"
      [[ "$refresh_choice" == "yes" ]] && refresh_instagram_session
    fi
  fi
  start_service
  cleanup_cache
  cat <<EOF

部署完成。

下一步在 Telegram 里这样用：
1. 私聊你的 bot，发送 /start
2. 你自己在私聊可以管理一切
3. 把 bot 拉进目标群
4. 你用管理员账号在群里发送 /enable_here
5. 群成员以后就可以用 /ig <Instagram链接>

常用运维命令：
  tg-ig-botctl status
  tg-ig-botctl logs
  tg-ig-botctl update
  tg-ig-botctl update-tools
  tg-ig-botctl cleanup
  tg-ig-botctl refresh-session
EOF
}

uninstall_everything() {
  local confirm
  confirm="$(prompt_value '这会停止服务并删除整个安装目录。确认请输入 DELETE' '')"
  [[ "$confirm" == "DELETE" ]] || die '已取消卸载。'
  run_root systemctl disable --now "$SERVICE_NAME" || true
  run_root systemctl disable --now "${WATCHDOG_NAME}.timer" || true
  run_root systemctl stop "${WATCHDOG_NAME}.service" || true
  run_root rm -f "$SERVICE_FILE" "$WATCHDOG_SERVICE_FILE" "$WATCHDOG_TIMER_FILE" "$ALERT_TEMPLATE_FILE" "$SYMLINK_PATH"
  run_root systemctl daemon-reload
  run_root rm -rf "$INSTALL_DIR"
  log '已完成卸载。'
}

menu() {
  while true; do
    cat <<'EOF'

========== tg-ig-bot 运维菜单 ==========
1. 安装 / 修复
2. 重新配置 .env
3. 刷新 Instagram session
4. 更新代码并重启
5. 仅更新下载工具
6. 重启服务
7. 查看状态
8. 查看日志
9. 清理缓存
10. 体检 doctor
11. 卸载
0. 退出
======================================
EOF
    local choice
    read -r -p '请选择: ' choice || true
    case "$choice" in
      1) install_or_repair ;;
      2) configure_env_interactive ;;
      3) refresh_instagram_session ;;
      4) update_code ;;
      5) update_downloader_tools ;;
      6) restart_service ;;
      7) show_status ;;
      8) show_logs ;;
      9) cleanup_cache ;;
      10) doctor ;;
      11) uninstall_everything ;;
      0) break ;;
      *) warn '无效选项' ;;
    esac
  done
}

main() {
  local command="${1:-menu}"
  shift || true
  parse_common_flags "$@"
  case "$command" in
    install) install_or_repair ;;
    configure) configure_env_interactive ;;
    refresh-session) refresh_instagram_session ;;
    update) update_code ;;
    update-tools) update_downloader_tools ;;
    restart) restart_service ;;
    start) start_service ;;
    stop) stop_service ;;
    status) show_status ;;
    logs) show_logs ;;
    cleanup) cleanup_cache ;;
    doctor) doctor ;;
    uninstall) uninstall_everything ;;
    internal-alert) internal_alert ;;
    internal-watchdog) internal_watchdog ;;
    menu) menu ;;
    -h|--help|help) usage ;;
    *) usage; die "未知命令：$command" ;;
  esac
}

main "$@"
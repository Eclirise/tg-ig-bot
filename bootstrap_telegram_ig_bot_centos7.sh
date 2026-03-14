#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'"'"'\n\t'"'"'

log() { echo "[bootstrap] $*"; }
warn() { echo "[bootstrap][WARN] $*" >&2; }
die() { echo "[bootstrap][ERROR] $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  bash bootstrap_telegram_ig_bot_centos7.sh --repo-url <git_url> [--branch main] [--install-dir /opt/tg-ig-bot]

Supports:
  CentOS 7, CentOS Stream 8/9, Oracle Linux, Rocky, Alma, RHEL 8+, Debian, Ubuntu

Examples:
  curl -fsSL https://raw.githubusercontent.com/Eclirise/tg-ig-bot/main/bootstrap_telegram_ig_bot_centos7.sh | \
    bash -s -- --repo-url https://github.com/Eclirise/tg-ig-bot.git --branch main --install-dir /opt/tg-ig-bot
EOF
}

if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

run_root() {
  if [[ -n "$SUDO" ]]; then
    log "$SUDO $*"
    $SUDO "$@"
  else
    log "$*"
    "$@"
  fi
}

OS_ID=""
OS_VERSION_ID=""
PKG_MGR=""

load_os_release() {
  if [[ -n "$OS_ID" ]]; then
    return
  fi
  [[ -f /etc/os-release ]] || die '当前系统缺少 /etc/os-release，无法识别发行版。'
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_VERSION_ID="${VERSION_ID:-0}"
  if command -v apt-get >/dev/null 2>&1; then
    PKG_MGR="apt-get"
  elif command -v dnf >/dev/null 2>&1; then
    PKG_MGR="dnf"
  elif command -v yum >/dev/null 2>&1; then
    PKG_MGR="yum"
  else
    die '未找到支持的包管理器，当前仅支持 apt-get / dnf / yum。'
  fi
}

prepare_centos7_repo() {
  load_os_release
  if [[ "$OS_ID" != "centos" || "${OS_VERSION_ID%%.*}" != "7" ]]; then
    return
  fi
  local marker="/etc/yum.repos.d/CentOS-Vault-7.9.2009.repo"
  if [[ -f "$marker" ]]; then
    return
  fi
  warn 'CentOS 7 已结束维护，脚本会切换到 vault 源。'
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

install_prerequisites() {
  load_os_release
  case "$PKG_MGR" in
    apt-get)
      run_root apt-get update
      run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y git curl
      ;;
    dnf)
      run_root dnf makecache -y
      run_root dnf install -y git curl
      ;;
    yum)
      run_root yum makecache -y
      run_root yum install -y git curl
      ;;
  esac
}

configure_firewall() {
  load_os_release
  case "$PKG_MGR" in
    apt-get) run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y firewalld >/dev/null 2>&1 || true ;;
    dnf) run_root dnf install -y firewalld >/dev/null 2>&1 || true ;;
    yum) run_root yum install -y firewalld >/dev/null 2>&1 || true ;;
  esac
  if command -v firewall-cmd >/dev/null 2>&1; then
    run_root systemctl enable firewalld >/dev/null 2>&1 || true
    run_root systemctl start firewalld >/dev/null 2>&1 || true
    run_root firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1 || true
    run_root firewall-cmd --reload >/dev/null 2>&1 || true
    log '已确保防火墙保留 SSH 访问。'
  fi
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

parse_args() {
  REPO_URL="${REPO_URL:-}"
  BRANCH="${BRANCH:-main}"
  INSTALL_DIR="${INSTALL_DIR:-/opt/tg-ig-bot}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo-url)
        [[ $# -ge 2 ]] || die '--repo-url 缺少参数。'
        REPO_URL="$2"
        shift 2
        ;;
      --branch)
        [[ $# -ge 2 ]] || die '--branch 缺少参数。'
        BRANCH="$2"
        shift 2
        ;;
      --install-dir)
        [[ $# -ge 2 ]] || die '--install-dir 缺少参数。'
        INSTALL_DIR="$2"
        shift 2
        ;;
      -h|--help|help)
        usage
        exit 0
        ;;
      *)
        die "未知参数：$1"
        ;;
    esac
  done
}

main() {
  parse_args "$@"
  prepare_centos7_repo
  install_prerequisites
  configure_firewall

  if [[ -z "$REPO_URL" ]]; then
    if [[ -t 0 ]]; then
      REPO_URL="$(prompt_value '请输入你的 GitHub 仓库克隆地址（HTTPS 或 SSH）')"
    else
      usage
      die '通过管道执行脚本时，必须用 --repo-url 指定仓库地址。'
    fi
  fi

  if [[ -t 0 ]]; then
    BRANCH="$(prompt_value '请输入分支名' "$BRANCH")"
    INSTALL_DIR="$(prompt_value '请输入安装目录' "$INSTALL_DIR")"
  fi

  [[ -n "$REPO_URL" ]] || die '仓库地址不能为空。'

  if [[ -d "$INSTALL_DIR/.git" ]]; then
    log '检测到已有仓库，准备更新。'
    run_root git -C "$INSTALL_DIR" fetch --all --tags --prune
    run_root git -C "$INSTALL_DIR" checkout "$BRANCH"
    run_root git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
  else
    run_root mkdir -p "$(dirname "$INSTALL_DIR")"
    run_root git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  fi

  [[ -f "$INSTALL_DIR/telegram_ig_bot/scripts/oracle_centos7_manager.sh" ]] || die '仓库中未找到 telegram_ig_bot/scripts/oracle_centos7_manager.sh。'
  bash "$INSTALL_DIR/telegram_ig_bot/scripts/oracle_centos7_manager.sh" install --repo-url "$REPO_URL" --branch "$BRANCH"
  bash "$INSTALL_DIR/telegram_ig_bot/scripts/oracle_centos7_manager.sh" fix-perms
  bash "$INSTALL_DIR/telegram_ig_bot/scripts/oracle_centos7_manager.sh" status
}

main "$@"

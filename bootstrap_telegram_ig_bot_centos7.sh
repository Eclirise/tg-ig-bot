#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'"'"'\n\t'"'"'

log() { echo "[bootstrap] $*"; }
warn() { echo "[bootstrap][WARN] $*" >&2; }
die() { echo "[bootstrap][ERROR] $*" >&2; exit 1; }

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

prepare_centos7_repo() {
  [[ -f /etc/centos-release ]] || die '当前系统不是 CentOS。'
  grep -q 'release 7' /etc/centos-release || die '当前系统不是 CentOS 7。'
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

configure_firewall() {
  run_root yum install -y firewalld >/dev/null 2>&1 || true
  if command -v firewall-cmd >/dev/null 2>&1; then
    run_root systemctl enable firewalld >/dev/null 2>&1 || true
    run_root systemctl start firewalld >/dev/null 2>&1 || true
    run_root firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1 || true
    run_root firewall-cmd --reload >/dev/null 2>&1 || true
    log '??????????? SSH?bot ??????????????????'
  fi
}

main() {
  prepare_centos7_repo
  run_root yum install -y git curl
  configure_firewall

  local repo_url branch install_dir
  read -r -p '请输入你的 GitHub 仓库克隆地址（HTTPS 或 SSH）: ' repo_url || true
  [[ -n "$repo_url" ]] || die '仓库地址不能为空。'
  read -r -p '请输入分支名 [main]: ' branch || true
  branch="${branch:-main}"
  read -r -p '请输入安装目录 [/opt/tg-ig-bot]: ' install_dir || true
  install_dir="${install_dir:-/opt/tg-ig-bot}"

  if [[ -d "$install_dir/.git" ]]; then
    log '检测到已有仓库，准备更新。'
    run_root git -C "$install_dir" fetch --all --tags --prune
    run_root git -C "$install_dir" checkout "$branch"
    run_root git -C "$install_dir" pull --ff-only origin "$branch"
  else
    run_root mkdir -p "$(dirname "$install_dir")"
    run_root git clone --depth 1 --branch "$branch" "$repo_url" "$install_dir"
  fi

  [[ -f "$install_dir/telegram_ig_bot/scripts/oracle_centos7_manager.sh" ]] || die '仓库中未找到 telegram_ig_bot/scripts/oracle_centos7_manager.sh。'
  bash "$install_dir/telegram_ig_bot/scripts/oracle_centos7_manager.sh" install --repo-url "$repo_url" --branch "$branch"
}

main "$@"
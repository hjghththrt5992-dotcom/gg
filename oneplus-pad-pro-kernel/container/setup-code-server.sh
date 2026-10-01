#!/usr/bin/env bash
# 在 Droidspaces 等容器里一键安装 code-server（浏览器里的 VS Code），平板上用浏览器打开即可，不需要 X11。
#
# 在容器里以 root 运行：
#   curl -fsSL https://raw.githubusercontent.com/hjghththrt5992-dotcom/gg/main/oneplus-pad-pro-kernel/container/setup-code-server.sh | bash -s -- [用户名]
#
# 用户名：以哪个用户运行 code-server，默认 root。
# 可选环境变量：PORT（默认 8080）、CS_VERSION（指定版本，如 4.139.1，默认最新）。
#
# 只监听 127.0.0.1，同一网络里的其他设备访问不到。Droidspaces 用默认的「主机模式」网络时，
# 容器和 Android 共用 127.0.0.1，平板浏览器直接打开 http://127.0.0.1:端口 就行。
set -euo pipefail

CS_USER="${1:-root}"
PORT="${PORT:-8080}"
CS_VERSION="${CS_VERSION:-}"
INSTALL_SH=https://raw.githubusercontent.com/coder/code-server/main/install.sh

die() { printf '\033[1;31m[错误] %s\033[0m\n' "$*" >&2; exit 1; }
log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "请用 root 运行（Droidspaces 终端默认就是 root）"
id "$CS_USER" >/dev/null 2>&1 || die "用户 $CS_USER 不存在，可先 useradd -m $CS_USER"
case "$PORT" in ''|*[!0-9]*) die "PORT 必须是数字" ;; esac
CS_HOME="$(getent passwd "$CS_USER" | cut -d: -f6)"

# ------------------------------------------------------------------ 1. 依赖
log "安装依赖（curl、证书）"
if command -v apt-get >/dev/null; then
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates >/dev/null
elif command -v dnf >/dev/null; then
  dnf install -y -q curl ca-certificates
elif command -v pacman >/dev/null; then
  pacman -Sy --noconfirm --needed curl ca-certificates >/dev/null
elif ! command -v curl >/dev/null; then
  die "不认识的包管理器，请先自行安装 curl"
fi

# ------------------------------------------------------------------ 2. code-server
# Debian / Ubuntu / Fedora 交给官方脚本（装 deb / rpm，自带 systemd 服务）；
# 其他发行版（Arch 的 AUR 不能用 root 装）用官方独立版装到 /usr/local。
. /etc/os-release
ARGS=()
[ -n "$CS_VERSION" ] && ARGS+=(--version "$CS_VERSION")
case " ${ID:-} ${ID_LIKE:-} " in
  *" debian "*|*" ubuntu "*|*" fedora "*|*" rhel "*) ;;
  *) ARGS+=(--method standalone --prefix /usr/local) ;;
esac
log "安装 code-server（${PRETTY_NAME:-未知发行版}）"
curl -fsSL "$INSTALL_SH" | sh -s -- ${ARGS[@]+"${ARGS[@]}"}
CS_BIN="$(command -v code-server || echo /usr/local/bin/code-server)"
[ -x "$CS_BIN" ] || die "没找到装好的 code-server"
"$CS_BIN" --config /dev/null --version | head -n1   # 指定空配置，否则它会顺手在 root 目录生成默认配置

# ------------------------------------------------------------------ 3. 配置
CFG="$CS_HOME/.config/code-server/config.yaml"
if [ -f "$CFG" ]; then
  log "保留已有配置 $CFG"
else
  log "生成配置：只监听 127.0.0.1:$PORT，随机密码"
  mkdir -p "$(dirname "$CFG")"
  PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-20)"
  cat > "$CFG" <<EOF
bind-addr: 127.0.0.1:$PORT
auth: password
password: $PASSWORD
cert: false
EOF
  chown -R "$CS_USER": "$CS_HOME/.config"
  chmod 600 "$CFG"
fi

# ------------------------------------------------------------------ 4. 开机自启
if [ -d /run/systemd/system ]; then
  if ! ls /etc/systemd/system/code-server@.service /usr/lib/systemd/system/code-server@.service \
         /lib/systemd/system/code-server@.service >/dev/null 2>&1; then
    cat > /etc/systemd/system/code-server@.service <<EOF
[Unit]
Description=code-server
After=network.target

[Service]
Type=exec
ExecStart=$CS_BIN
Restart=always
User=%i

[Install]
WantedBy=default.target
EOF
    systemctl daemon-reload
  fi
  systemctl enable --now "code-server@$CS_USER"
  sleep 2
  systemctl is-active --quiet "code-server@$CS_USER" || die "code-server 没能启动，查看日志：journalctl -u code-server@$CS_USER"
  START_HINT="已设为开机自启（容器启动时自动运行）"
else
  START_HINT="容器里没有 systemd，需要手动启动：su $CS_USER -c '$CS_BIN' &"
fi

# ------------------------------------------------------------------ 5. 完成
BIND="$(sed -n 's/^bind-addr: *//p' "$CFG")"
PASS="$(sed -n 's/^password: *//p' "$CFG")"
log "完成"
cat <<EOF
  地址：http://$BIND
  密码：${PASS:-（见 $CFG）}
  $START_HINT

  在平板浏览器打开上面的地址，输入密码即可。
  Chrome 菜单里选「添加到主屏幕」或「安装应用」，之后就像独立 App 一样全屏打开。
  改密码：编辑 $CFG 后重启容器。
EOF

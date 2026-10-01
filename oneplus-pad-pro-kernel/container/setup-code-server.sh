#!/usr/bin/env bash
# 在 Droidspaces 等容器里一键安装 code-server（浏览器里的 VS Code），平板上用浏览器打开即可，不需要 X11。
#
# 在容器里以 root 运行（容器配置里打开「Android 存储」，把本脚本存到平板的「下载」文件夹）：
#   bash /storage/emulated/0/Download/setup-code-server.sh [用户名]
# 能访问 GitHub 时也可以直接：
#   curl -fsSL https://raw.githubusercontent.com/hjghththrt5992-dotcom/gg/main/oneplus-pad-pro-kernel/container/setup-code-server.sh | bash -s -- [用户名]
#
# 用户名：以哪个用户运行 code-server，默认 root。
# 可选环境变量：
#   PORT          端口，默认 8080
#   CS_SOURCE     下载源：auto（默认，先试 GitHub，连不上换中科大镜像）/ github / ustc
#   CS_VERSION    指定版本（如 4.139.1），只对 GitHub 有效，中科大镜像只保留最新版
#   CS_PKG_FILE   事先下载好的安装包路径（.deb 或 linux-*.tar.gz），设置后完全不联网下载
#
# 只监听 127.0.0.1，同一网络里的其他设备访问不到。Droidspaces 用默认的「主机模式」网络时，
# 容器和 Android 共用 127.0.0.1，平板浏览器直接打开 http://127.0.0.1:端口 就行。
set -euo pipefail

CS_USER="${1:-root}"
PORT="${PORT:-8080}"
CS_SOURCE="${CS_SOURCE:-auto}"
CS_VERSION="${CS_VERSION:-}"
CS_PKG_FILE="${CS_PKG_FILE:-}"
GITHUB_BASE=https://github.com/coder/code-server/releases
USTC_BASE="${USTC_BASE:-https://mirrors.ustc.edu.cn/github-release/coder/code-server/LatestRelease}"

die() { printf '\033[1;31m[错误] %s\033[0m\n' "$*" >&2; exit 1; }
log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "请用 root 运行（Droidspaces 终端默认就是 root）"
id "$CS_USER" >/dev/null 2>&1 || die "用户 $CS_USER 不存在，可先 useradd -m $CS_USER"
case "$PORT" in ''|*[!0-9]*) die "PORT 必须是数字" ;; esac
CS_HOME="$(getent passwd "$CS_USER" | cut -d: -f6)"

case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  x86_64|amd64) ARCH=amd64 ;;
  *) die "不支持的架构：$(uname -m)" ;;
esac
# Debian / Ubuntu 装官方 deb 包（没有依赖，自带 systemd 服务）；其他发行版用官方独立版压缩包
if command -v dpkg >/dev/null; then KIND=deb; else KIND=tar; fi

# ------------------------------------------------------------------ 1. 依赖
if [ -z "$CS_PKG_FILE" ] && ! command -v curl >/dev/null; then
  log "安装 curl"
  if command -v apt-get >/dev/null; then
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates >/dev/null
  elif command -v dnf >/dev/null; then
    dnf install -y -q curl ca-certificates
  elif command -v pacman >/dev/null; then
    pacman -Sy --noconfirm --needed curl ca-certificates >/dev/null
  else
    die "不认识的包管理器，请先自行安装 curl"
  fi
fi

# ------------------------------------------------------------------ 2. 找安装包
pkg_name() {  # $1=版本
  if [ "$KIND" = deb ]; then echo "code-server_${1}_${ARCH}.deb"; else echo "code-server-${1}-linux-${ARCH}.tar.gz"; fi
}

resolve_github() {
  local v="$CS_VERSION"
  if [ -z "$v" ]; then
    v="$(curl -fsSI --connect-timeout 8 --max-time 20 "$GITHUB_BASE/latest" 2>/dev/null |
         sed -n 's|^[Ll]ocation: .*/tag/v\([0-9.]*\).*|\1|p' | tr -d '\r')" || true
  fi
  [ -n "$v" ] || return 1
  URL="$GITHUB_BASE/download/v$v/$(pkg_name "$v")"
  VERSION="$v"
  curl -fsSIL --connect-timeout 8 --max-time 30 -o /dev/null "$URL" 2>/dev/null   # 确认真的能下载
}

resolve_ustc() {
  local listing pattern file
  listing="$(curl -fsSL --connect-timeout 8 --max-time 30 "$USTC_BASE/" 2>/dev/null)" || return 1
  if [ "$KIND" = deb ]; then pattern="code-server_[0-9.]+_${ARCH}\\.deb"; else pattern="code-server-[0-9.]+-linux-${ARCH}\\.tar\\.gz"; fi
  file="$(printf '%s\n' "$listing" | grep -oE "href=\"$pattern\"" | head -n1 | sed 's/^href="//; s/"$//')" || true
  [ -n "$file" ] || return 1
  VERSION="$(printf '%s\n' "$file" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
  if [ -n "$CS_VERSION" ] && [ "$CS_VERSION" != "$VERSION" ]; then
    echo "中科大镜像只保留最新版 $VERSION，忽略 CS_VERSION=$CS_VERSION"
  fi
  URL="$USTC_BASE/$file"
}

if [ -n "$CS_PKG_FILE" ]; then
  [ -f "$CS_PKG_FILE" ] || die "找不到安装包 $CS_PKG_FILE"
  case "$CS_PKG_FILE" in
    *.deb) KIND=deb ;;
    *.tar.gz) KIND=tar ;;
    *) die "CS_PKG_FILE 只能是 .deb 或 .tar.gz" ;;
  esac
  PKG="$CS_PKG_FILE"
  log "使用本地安装包 $PKG"
else
  case "$CS_SOURCE" in
    github) resolve_github || die "连不上 GitHub" ; SRC=GitHub ;;
    ustc) resolve_ustc || die "连不上中科大镜像" ; SRC=中科大镜像 ;;
    auto)
      if resolve_github; then SRC=GitHub
      elif echo "GitHub 连不上，改用中科大镜像" && resolve_ustc; then SRC=中科大镜像
      else
        die "GitHub 和中科大镜像都连不上。可以用浏览器下载 $(pkg_name '<版本>') 到平板，再用 CS_PKG_FILE=文件路径 运行本脚本"
      fi ;;
    *) die "CS_SOURCE 只能是 auto / github / ustc" ;;
  esac
  log "从 $SRC 下载 code-server $VERSION（$ARCH）"
  PKG="$(mktemp -d)/$(basename "$URL")"
  curl -fL --retry 3 --connect-timeout 15 -o "$PKG" "$URL"
fi

# ------------------------------------------------------------------ 3. 安装
log "安装 code-server"
if [ "$KIND" = deb ]; then
  dpkg -i "$PKG" >/dev/null
  CS_BIN=/usr/bin/code-server
else
  mkdir -p /usr/local/lib /usr/local/bin
  tar -xzf "$PKG" -C /usr/local/lib
  CS_BIN="/usr/local/lib/$(basename "$PKG" .tar.gz)/bin/code-server"
  ln -sfn "$CS_BIN" /usr/local/bin/code-server
fi
[ -x "$CS_BIN" ] || die "没找到装好的 code-server（$CS_BIN）"
"$CS_BIN" --config /dev/null --version | head -n1   # 指定空配置，否则它会顺手在 root 目录生成默认配置

# ------------------------------------------------------------------ 4. 配置
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

# ------------------------------------------------------------------ 5. 开机自启
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

# ------------------------------------------------------------------ 6. 完成
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

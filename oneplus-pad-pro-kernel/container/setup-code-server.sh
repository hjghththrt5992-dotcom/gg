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
#   PORT          端口，默认 8080（重复运行时沿用上次的端口）
#   CS_SOURCE     下载源：auto（默认，先试 GitHub，连不上换中科大镜像）/ github / ustc
#   CS_VERSION    指定版本（如 4.139.1），只对 GitHub 有效，中科大镜像只保留最新版
#   CS_PKG_FILE   事先下载好的安装包路径（.deb 或 linux-*.tar.gz），设置后完全不联网下载
#   CS_REINSTALL  =1 时即使已经装过也重新下载安装（默认装过就跳过，只更新配置并重启）
#
# 脚本会读取 Droidspaces 的网络模式（容器里的 /run/droidspaces/container.config）：
#   主机模式：容器和 Android 共用 127.0.0.1，只监听 127.0.0.1，同一 WiFi 里的其他设备访问不到。
#   NAT 模式（Droidspaces 新建容器的默认值）：容器有自己的 127.0.0.1，平板浏览器连不进来，
#     需要在容器配置里加端口转发；脚本会改为监听容器自己的网卡并打印能用的地址。
# 重复运行是安全的：不会重新下载、不会改密码，只按当前网络模式调整监听地址并重启 code-server。
set -euo pipefail

CS_USER="${1:-root}"
PORT_SET="${PORT:+yes}"
PORT="${PORT:-8080}"
CS_SOURCE="${CS_SOURCE:-auto}"
CS_VERSION="${CS_VERSION:-}"
CS_PKG_FILE="${CS_PKG_FILE:-}"
CS_REINSTALL="${CS_REINSTALL:-0}"
GITHUB_BASE=https://github.com/coder/code-server/releases
USTC_BASE="${USTC_BASE:-https://mirrors.ustc.edu.cn/github-release/coder/code-server/LatestRelease}"
DS_CFG="${DS_CFG:-/run/droidspaces/container.config}"

die() { printf '\033[1;31m[错误] %s\033[0m\n' "$*" >&2; exit 1; }
log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[注意] %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "请用 root 运行（Droidspaces 终端默认就是 root）"
id "$CS_USER" >/dev/null 2>&1 || die "用户 $CS_USER 不存在，可先 useradd -m $CS_USER"
case "$PORT" in ''|*[!0-9]*) die "PORT 必须是数字" ;; esac
CS_HOME="$(getent passwd "$CS_USER" | cut -d: -f6)"
CFG="$CS_HOME/.config/code-server/config.yaml"

# 重复运行且没指定 PORT 时，沿用已有配置里的端口
if [ -z "$PORT_SET" ] && [ -f "$CFG" ]; then
  OLD_PORT="$(sed -n 's/^bind-addr: *.*:\([0-9][0-9]*\) *$/\1/p' "$CFG" | head -n1)"
  PORT="${OLD_PORT:-$PORT}"
fi

case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  x86_64|amd64) ARCH=amd64 ;;
  *) die "不支持的架构：$(uname -m)" ;;
esac
# Debian / Ubuntu 装官方 deb 包（没有依赖，自带 systemd 服务）；其他发行版用官方独立版压缩包
if command -v dpkg >/dev/null; then KIND=deb; else KIND=tar; fi

# ------------------------------------------------------------------ 0. 网络模式
# 不是 Droidspaces 容器（没有这个文件）时按共用网络处理
NET_MODE=host
if [ -r "$DS_CFG" ]; then
  NET_MODE="$(sed -n 's/^net_mode=//p' "$DS_CFG" | tail -n1)"
  NET_MODE="${NET_MODE:-host}"
fi

# Droidspaces 的端口转发写成 port_forwards=8080:8080/tcp,9000-9010:9000-9010/tcp，
# 找出转发到容器 $PORT 的那个主机端口
forwarded_host_port() {
  local list item hp cp hs he cs ce
  [ -r "$DS_CFG" ] || return 1
  list="$(sed -n 's/^port_forwards=//p' "$DS_CFG" | tail -n1)"
  [ -n "$list" ] || return 1
  IFS=, read -ra items <<< "$list"
  for item in "${items[@]}"; do
    case "$item" in */tcp|*[0-9]) ;; *) continue ;; esac   # 只要 TCP
    item="${item%/*}"
    hp="${item%%:*}"; cp="${item#*:}"
    hs="${hp%-*}"; he="${hp#*-}"; cs="${cp%-*}"; ce="${cp#*-}"
    case "$hs$he$cs$ce" in ''|*[!0-9]*) continue ;; esac
    if [ "$PORT" -ge "$cs" ] && [ "$PORT" -le "$ce" ]; then
      echo $((hs + PORT - cs)); return 0
    fi
  done
  return 1
}

container_ip() {
  local ip=""
  if command -v hostname >/dev/null; then ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || true; fi
  if [ -z "$ip" ] && command -v ip >/dev/null; then
    ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4; exit}')" || true
  fi
  if [ -z "$ip" ] && [ -r "$DS_CFG" ]; then
    ip="$(sed -n 's/^static_nat_ip=//p' "$DS_CFG" | cut -d/ -f1)"
  fi
  echo "${ip:-<容器IP>}"
}

case "$NET_MODE" in
  host)
    BIND_IP=127.0.0.1 ;;
  nat|gateway)
    # 容器有自己的网络，127.0.0.1 只在容器里有效。监听容器自己的网卡，Android 才能连进来；
    # 同一 WiFi 的其他设备只有在 Droidspaces 里配了端口转发时才能连到（都要密码）。
    BIND_IP=0.0.0.0 ;;
  none)
    die "这个容器的网络模式是「无（完全隔离）」，平板浏览器连不进来。请在 Droidspaces → 编辑容器配置 → 网络 → 网络模式 改成「主机」，重启容器后再运行本脚本" ;;
  *)
    warn "不认识的网络模式 $NET_MODE，按主机模式处理"
    NET_MODE=host; BIND_IP=127.0.0.1 ;;
esac
log "容器网络模式：$NET_MODE，code-server 监听 $BIND_IP:$PORT"

# ------------------------------------------------------------------ 1-3. 下载并安装
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

install_code_server() {
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
}

CS_BIN=""
for b in /usr/bin/code-server /usr/local/bin/code-server; do
  if [ -x "$b" ]; then CS_BIN="$b"; break; fi
done
if [ -n "$CS_BIN" ] && [ -z "$CS_PKG_FILE$CS_VERSION" ] && [ "$CS_REINSTALL" != 1 ]; then
  log "code-server 已经装好（$CS_BIN），跳过下载；要重装或升级请加 CS_REINSTALL=1"
else
  install_code_server
fi
[ -x "$CS_BIN" ] || die "没找到装好的 code-server（$CS_BIN）"
"$CS_BIN" --config /dev/null --version | head -n1   # 指定空配置，否则它会顺手在 root 目录生成默认配置

# ------------------------------------------------------------------ 4. 配置
if [ -f "$CFG" ]; then
  OLD_BIND="$(sed -n 's/^bind-addr: *//p' "$CFG" | head -n1)"
  if [ "$OLD_BIND" = "$BIND_IP:$PORT" ]; then
    log "保留已有配置 $CFG"
  else
    log "监听地址 ${OLD_BIND:-（未设置）} → $BIND_IP:$PORT（密码不变）"
    if grep -q '^bind-addr:' "$CFG"; then
      sed -i "s|^bind-addr:.*|bind-addr: $BIND_IP:$PORT|" "$CFG"
    else
      printf 'bind-addr: %s\n' "$BIND_IP:$PORT" >> "$CFG"
    fi
  fi
else
  log "生成配置：监听 $BIND_IP:$PORT，随机密码"
  mkdir -p "$(dirname "$CFG")"
  PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-20)"
  cat > "$CFG" <<EOF
bind-addr: $BIND_IP:$PORT
auth: password
password: $PASSWORD
cert: false
EOF
  chown -R "$CS_USER": "$CS_HOME/.config"
  chmod 600 "$CFG"
fi

# ------------------------------------------------------------------ 5. 启动
port_up() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }

# 停掉之前手动启动的 code-server（改了配置要重启才生效）。按进程命令行认，
# 不用 pkill -f code-server，那样会把正在运行的本脚本也杀掉
stop_manual() {
  local d cmd killed=0
  for d in /proc/[0-9]*; do
    cmd="$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)" || continue
    case "$cmd" in
      *code-server*/lib/node\ *) kill "${d#/proc/}" 2>/dev/null && killed=1 ;;
    esac
  done
  [ "$killed" = 1 ] || return 0
  for _ in 1 2 3 4 5 6 7 8 9 10; do port_up || return 0; sleep 1; done
}

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
  systemctl stop "code-server@$CS_USER" 2>/dev/null || true
  stop_manual
  systemctl enable "code-server@$CS_USER" >/dev/null 2>&1 || true
  systemctl start "code-server@$CS_USER" || true   # 起不来时下面的检查会打印日志
  START_HINT="已设为开机自启（容器启动时自动运行）"
  SHOW_LOG="journalctl -u code-server@$CS_USER -n 30 --no-pager"
else
  # 没有 systemd：生成一个启动命令，现在先跑一次，以后每次启动容器后运行 code-server-start
  CS_LOG=/var/log/code-server.log
  cat > /usr/local/bin/code-server-start <<EOF
#!/bin/sh
# 由 setup-code-server.sh 生成：容器里没有 systemd，每次启动容器后运行一次 code-server-start
for d in /proc/[0-9]*; do   # 先停掉已经在跑的
  case "\$(tr '\\0' ' ' < "\$d/cmdline" 2>/dev/null)" in
    *code-server*/lib/node\\ *) kill "\${d#/proc/}" 2>/dev/null ;;
  esac
done
sleep 1
if [ "$CS_USER" = root ]; then
  setsid "$CS_BIN" >>$CS_LOG 2>&1 </dev/null &
else
  setsid su "$CS_USER" -s /bin/sh -c 'exec "$CS_BIN"' >>$CS_LOG 2>&1 </dev/null &
fi
echo "code-server 已在后台启动，日志：$CS_LOG"
EOF
  chmod 755 /usr/local/bin/code-server-start
  stop_manual
  /usr/local/bin/code-server-start >/dev/null
  START_HINT="容器里没有 systemd，不会自动启动：以后每次启动容器后运行一次 code-server-start"
  SHOW_LOG="tail -n 30 $CS_LOG"
fi

log "等待 code-server 启动"
for _ in $(seq 1 40); do port_up && break; sleep 1; done
if ! port_up; then
  echo "最近的日志："
  $SHOW_LOG || true
  die "code-server 40 秒内没有开始监听端口 $PORT，看上面的日志找原因"
fi
echo "code-server 已在容器里监听 $BIND_IP:$PORT"

# ------------------------------------------------------------------ 6. 完成
PASS="$(sed -n 's/^password: *//p' "$CFG")"
log "完成"
if [ "$NET_MODE" = host ]; then
  ADDR="http://127.0.0.1:$PORT"
  NOTE="容器和 Android 共用网络，只有本机能打开。"
elif [ "$NET_MODE" = nat ] && HOST_PORT="$(forwarded_host_port)"; then
  ADDR="http://127.0.0.1:$HOST_PORT"
  NOTE="经 Droidspaces 端口转发（主机 $HOST_PORT → 容器 $PORT）访问。
  同一 WiFi 下的其他设备用「平板IP:$HOST_PORT」也能打开登录页，靠密码保护。"
else
  ADDR="http://$(container_ip):$PORT"
  NOTE="容器是 $NET_MODE 网络（Droidspaces 新建容器默认是 NAT），和 Android 不共用 127.0.0.1，
  所以 http://127.0.0.1:$PORT 会显示「拒绝连接」。上面是容器自己的地址，可以先用；
  但浏览器把它当成不安全来源，Markdown 预览、扩展页面、剪贴板可能用不了。
  完整体验二选一（在 Droidspaces → 编辑容器配置 → 网络 里改）：
    a) 端口转发 → 添加端口转发，填 $PORT（保留网络隔离，推荐）
    b) 网络模式 改成「主机」（只有本机能打开）
  改完重启容器，再运行一次本脚本（不会重新下载），它会打印 http://127.0.0.1 开头的地址。"
fi
cat <<EOF
  地址：$ADDR
  密码：${PASS:-（见 $CFG）}
  $NOTE
  $START_HINT

  在平板浏览器打开上面的地址，输入密码即可。
  Chrome 菜单里选「添加到主屏幕」或「安装应用」，之后就像独立 App 一样全屏打开。
  改密码：编辑 $CFG 后重新运行本脚本（或重启容器）。
EOF

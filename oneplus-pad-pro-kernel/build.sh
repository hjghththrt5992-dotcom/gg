#!/usr/bin/env bash
# 一加平板 Pro（OnePlus Pad Pro，骁龙 8 Gen 3 / SM8650 / pineapple）GKI 玩机内核一键编译脚本
#
# 源码：OnePlusOSS/android_kernel_common_oneplus_sm8650（一加官方开源的 GKI 通用内核，android14-6.1）
# 产物（$OUT_DIR）：
#   Image                   原始内核镜像
#   <名称>-AnyKernel3.zip   卡刷包（Kernel Flasher / Horizon Kernel Flasher / SukiSU 管理器 / 第三方 Recovery 刷入）
#   <名称>-boot.img         仅当提供 STOCK_BOOT（官方 boot.img）时生成，可直接 fastboot 刷入
#   build-info.txt          本次编译的版本信息
#
# 所有参数都可以用环境变量覆盖，例如：
#   ANDROID_VER=15 SUSFS=false ./build.sh
set -euo pipefail

# ------------------------------------------------------------------ 参数
ANDROID_VER="${ANDROID_VER:-16}"            # 平板当前系统的安卓大版本：14 / 15 / 16
KSU="${KSU:-true}"                           # 集成 KernelSU（官方 tiann/KernelSU）；false = 通用内核，可配合 APatch / Magisk
KSU_REF="${KSU_REF:-main}"                   # KernelSU 分支 / tag / commit
SUSFS="${SUSFS:-true}"                       # 集成 SUSFS 隐藏 root（需要 KSU=true）
SUSFS_REF="${SUSFS_REF:-gki-android14-6.1}"  # SUSFS 分支 / commit
BBR="${BBR:-true}"                           # 编入 BBR 拥塞控制算法
BBR3="${BBR3:-true}"                          # 回合 BBRv3（比 BBRv1 更新，需要打补丁）
BBR_DEFAULT="${BBR_DEFAULT:-false}"          # 把 BBR 设为默认拥塞控制
NET_EXTRAS="${NET_EXTRAS:-true}"             # TTL/HL 修改 + ipset（热点、代理、防火墙类模块会用到）
QDISC="${QDISC:-true}"                        # 编入 FQ/FQ_CODEL/CAKE/PIE 等队列调度（降低网络延迟）
OPT="${OPT:-true}"                            # 一组社区调优补丁（内存/调度/文件系统/功耗，见文档）
O3="${O3:-false}"                             # 用 -O3 而不是 -O2 编译（更激进，体积更大，未必更快）
NTSYNC="${NTSYNC:-false}"                     # NTSync 同步原语（跑 Wine/游戏兼容层时有用）
TMPFS_XATTR="${TMPFS_XATTR:-true}"            # tmpfs 的 xattr / POSIX ACL（部分模块和容器需要）
CONTAINERS="${CONTAINERS:-false}"             # 容器支持（LXC / Docker / Podman）：PID/IPC/USER 命名空间、SYSVIPC 等
ABI_CHECK="${ABI_CHECK:-true}"                # 额外编一个官方配置的基线，核对 KMI 符号 CRC，不一致就不出包
LTO="${LTO:-thin}"                           # none / thin / full（full 最慢，体积最小）
PATCHES_REF="${PATCHES_REF:-41ae18b35d20e0c6ac04116785a4a1089528ae94}"  # WildKernels/kernel_patches 固定 commit
LOCALVERSION_STR="${LOCALVERSION_STR:--android14-11}"  # uname -r 中 6.1.x 之后的后缀
KERNEL_NAME="${KERNEL_NAME:-OPPadPro-GKI}"   # 刷包文件名前缀
BUILD_USER="${BUILD_USER:-kleaf}"            # uname -v 中的编译用户，与官方保持一致
BUILD_HOST="${BUILD_HOST:-build-host}"       # uname -v 中的编译主机，与官方保持一致
STOCK_BOOT="${STOCK_BOOT:-}"                 # 可选：与平板当前系统版本一致的官方 boot.img
CLANG_DIR="${CLANG_DIR:-}"                   # 可选：自备 clang 的 bin 目录；留空则下载一加同款 clang
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${WORK_DIR:-$SCRIPT_DIR/work}"
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/dist}"
JOBS="${JOBS:-$(nproc)}"

# 系统大版本 -> OnePlusOSS/kernel_manifest（oneplus/sm8650 分支）里一加平板 Pro 的清单
case "$ANDROID_VER" in
  14) MANIFEST=oneplus_pad_pro.xml ;;
  15) MANIFEST=oneplus_pad_pro_v.xml ;;
  16) MANIFEST=oneplus_pad_pro_b.xml ;;
  *) echo "ANDROID_VER 只能是 14 / 15 / 16" >&2; exit 1 ;;
esac
MANIFEST_URL="https://raw.githubusercontent.com/OnePlusOSS/kernel_manifest/oneplus/sm8650/$MANIFEST"
KERNEL_REPO=https://github.com/OnePlusOSS/android_kernel_common_oneplus_sm8650.git
SUSFS_REPO=https://gitlab.com/simonpunk/susfs4ksu.git
AK3_REPO=https://github.com/osm0sis/AnyKernel3.git
PATCHES_REPO=https://github.com/WildKernels/kernel_patches.git

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[错误] %s\033[0m\n' "$*" >&2; exit 1; }

if [ "$KSU" != true ] && [ "$SUSFS" = true ]; then
  echo "KSU=false：编译通用内核，SUSFS 依赖 KernelSU，已自动关闭"
  SUSFS=false
fi
for tool in git curl python3 make bc bison flex zip pahole; do
  command -v "$tool" >/dev/null || die "缺少 $tool，Ubuntu 可执行：sudo apt install git curl python3 make bc bison flex zip dwarves libssl-dev libelf-dev cpio"
done

mkdir -p "$WORK_DIR" "$OUT_DIR"
KP="$WORK_DIR/a$ANDROID_VER/kernel_platform"   # 目录结构与官方 repo 同步后一致
KDIR="$KP/common"
KOUT="$WORK_DIR/a$ANDROID_VER/out"

# ------------------------------------------------------------------ 1. 读取官方清单
log "读取官方清单 $MANIFEST"
curl -fsSL "$MANIFEST_URL" -o "$WORK_DIR/manifest.xml"
read -r KERNEL_BRANCH VENDOR_BRANCH CLANG_REMOTE CLANG_REV < <(python3 - "$WORK_DIR/manifest.xml" <<'EOF'
import sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
remotes = {r.get("name"): r.get("fetch").rstrip("/") for r in root.iter("remote")}
default = root.find("default")
kernel = vendor = clang = None
for p in root.iter("project"):
    if p.get("name") == "android_kernel_common_oneplus_sm8650":
        kernel = p.get("revision")
    if p.get("name") == "android_kernel_modules_and_devicetree_oneplus_sm8650":
        vendor = p.get("revision")
    if p.get("path") == "kernel_platform/prebuilts/clang/host/linux-x86":
        remote = remotes[p.get("remote") or default.get("remote")]
        clang = (f"{remote}/{p.get('name')}.git", p.get("revision"))
print(kernel, vendor, *clang)
EOF
)
echo "内核分支: $KERNEL_BRANCH"

# ------------------------------------------------------------------ 2. 拉取 / 重置内核源码
if [ -d "$KDIR/.git" ] && [ "$(git -C "$KDIR" rev-parse --abbrev-ref HEAD)" = "$KERNEL_BRANCH" ]; then
  log "更新已有源码并还原为干净状态"
  git -C "$KDIR" fetch -q --depth=1 origin "$KERNEL_BRANCH"
  git -C "$KDIR" reset -q --hard FETCH_HEAD
  git -C "$KDIR" clean -qfdx
else
  log "克隆内核源码（浅克隆）"
  rm -rf "$KP"
  mkdir -p "$KP"
  git clone --depth=1 -b "$KERNEL_BRANCH" "$KERNEL_REPO" "$KDIR"
fi
rm -rf "$KP/KernelSU" "$WORK_DIR/susfs"
KERNEL_VERSION="$(make -s -C "$KDIR" kernelversion)"
echo "内核版本: $KERNEL_VERSION"

# 一加在 common 里用软链接引用了另一个仓库（modules_and_devicetree）中 vendor/oplus 下的源码，
# 不补齐的话 Kconfig 直接报错。这里只稀疏检出被引用到的那几个目录（几 MB），不拉整个仓库
SRC_ROOT="$(dirname "$KP")"
mapfile -t VENDOR_PATHS < <(
  cd "$KDIR"
  git ls-files -s | awk '$1 == "120000" {print $4}' | while read -r link; do
    target="$(realpath -m --relative-to="$SRC_ROOT" "$(dirname "$link")/$(readlink "$link")")"
    case "$target" in vendor/*) echo "/$target" ;; esac
  done | sort -u
)
if [ "${#VENDOR_PATHS[@]}" -gt 0 ]; then
  log "拉取 common 引用的一加 vendor 源码"
  VENDOR_DIR="$SRC_ROOT/oplus-vendor"
  rm -rf "$VENDOR_DIR" "$SRC_ROOT/vendor"
  mkdir -p "$VENDOR_DIR"
  git -C "$VENDOR_DIR" init -q
  git -C "$VENDOR_DIR" remote add origin https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8650.git
  git -C "$VENDOR_DIR" sparse-checkout set --no-cone "${VENDOR_PATHS[@]}"
  git -C "$VENDOR_DIR" fetch -q --depth=1 --filter=blob:none origin "$VENDOR_BRANCH"
  git -C "$VENDOR_DIR" checkout -q FETCH_HEAD
  ln -s oplus-vendor/vendor "$SRC_ROOT/vendor"
  printf '  %s\n' "${VENDOR_PATHS[@]}"
fi

# ------------------------------------------------------------------ 3. 工具链：一加同款 clang
if [ -z "$CLANG_DIR" ]; then
  CLANG_VERSION="$(sed -n 's/^CLANG_VERSION=//p' "$KDIR/build.config.constants")"   # 例如 r487747c
  CLANG_ROOT="$WORK_DIR/clang-$CLANG_VERSION"
  CLANG_DIR="$CLANG_ROOT/clang-$CLANG_VERSION/bin"
  if [ ! -x "$CLANG_DIR/clang" ]; then
    log "下载 clang-$CLANG_VERSION"
    rm -rf "$CLANG_ROOT"
    mkdir -p "$CLANG_ROOT"
    # 首选：一加清单锁定的 CodeLinaro 提交，只检出需要的那个 clang 目录
    if ! {
      git -C "$CLANG_ROOT" init -q &&
      git -C "$CLANG_ROOT" remote add origin "$CLANG_REMOTE" &&
      git -C "$CLANG_ROOT" sparse-checkout set --no-cone "/clang-$CLANG_VERSION/" &&
      git -C "$CLANG_ROOT" fetch -q --depth=1 --filter=blob:none origin "$CLANG_REV" &&
      git -C "$CLANG_ROOT" checkout -q FETCH_HEAD
    }; then
      # 备用：AOSP android14-release 分支里的同版本 clang
      echo "CodeLinaro 下载失败，改用 AOSP 源"
      rm -rf "$CLANG_ROOT"
      mkdir -p "$CLANG_ROOT/clang-$CLANG_VERSION"
      curl -fL --retry 3 "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/refs/heads/android14-release/clang-$CLANG_VERSION.tar.gz" |
        tar -xz -C "$CLANG_ROOT/clang-$CLANG_VERSION"
    fi
  fi
fi
[ -x "$CLANG_DIR/clang" ] || die "找不到 clang：$CLANG_DIR/clang，可用 CLANG_DIR 指定自备工具链"
export PATH="$CLANG_DIR:$PATH"
clang --version | head -n1

export KBUILD_BUILD_USER="$BUILD_USER" KBUILD_BUILD_HOST="$BUILD_HOST"
MAKE_BASE=(-C "$KDIR" ARCH=arm64 LLVM=1 LLVM_IAS=1 LOCALVERSION=)
if command -v ccache >/dev/null; then
  MAKE_BASE+=(CC="ccache clang" HOSTCC="ccache clang")
fi
set_lto() {  # $1=.config 路径
  local c=("$KDIR/scripts/config" --file "$1")
  case "$LTO" in
    none) "${c[@]}" -e LTO_NONE -d LTO_CLANG_THIN -d LTO_CLANG_FULL ;;
    thin) "${c[@]}" -d LTO_NONE -e LTO_CLANG_THIN -d LTO_CLANG_FULL ;;
    full) "${c[@]}" -d LTO_NONE -d LTO_CLANG_THIN -e LTO_CLANG_FULL ;;
    *) die "LTO 只能是 none / thin / full" ;;
  esac
}

# ------------------------------------------------------------------ 3.5 ABI 基线
# 厂商模块只认官方内核导出的 KMI 符号及其 CRC。这里用「官方源码 + 官方配置」编一个基线，
# 编完正式内核后逐个比对 KMI 符号的 CRC（见 abi_check.py）。基线按源码 commit 缓存，只编一次。
BASE_SYMVERS=""
if [ "$ABI_CHECK" = true ]; then
  CC_ID="$(clang --version | head -n1 | md5sum | cut -c1-8)"   # 换编译器就重编基线
  BASE_SYMVERS="$WORK_DIR/abi-baseline-a$ANDROID_VER-$(git -C "$KDIR" rev-parse --short=12 HEAD)-lto-$LTO-cc-$CC_ID.symvers"
  if [ -s "$BASE_SYMVERS" ]; then
    log "复用 ABI 基线 $(basename "$BASE_SYMVERS")"
  else
    log "编译 ABI 基线（官方源码 + 官方配置，只用来核对符号 CRC）"
    BOUT="$WORK_DIR/a$ANDROID_VER/out-baseline"
    rm -rf "$BOUT"
    make "${MAKE_BASE[@]}" O="$BOUT" gki_defconfig
    set_lto "$BOUT/.config"
    make "${MAKE_BASE[@]}" O="$BOUT" olddefconfig
    make "${MAKE_BASE[@]}" O="$BOUT" -j"$JOBS" vmlinux
    cp "$BOUT/vmlinux.symvers" "$BASE_SYMVERS"
    rm -rf "$BOUT"
  fi
fi

# ------------------------------------------------------------------ 4. KernelSU
if [ "$KSU" = true ]; then
  log "集成 KernelSU ($KSU_REF)"
  (cd "$KP" && curl -fsSL "https://raw.githubusercontent.com/tiann/KernelSU/main/kernel/setup.sh" | bash -s "$KSU_REF")
  # setup.sh 在检出失败时只打印提示并回退到默认分支，这里显式确认
  if [ "$KSU_REF" != main ]; then
    [ "$(git -C "$KP/KernelSU" rev-parse HEAD)" = "$(git -C "$KP/KernelSU" rev-parse "$KSU_REF^{commit}")" ] ||
      die "KernelSU 未能检出 $KSU_REF"
  fi
fi

# ------------------------------------------------------------------ 5. SUSFS
if [ "$SUSFS" = true ]; then
  log "集成 SUSFS ($SUSFS_REF)"
  git clone -q -b gki-android14-6.1 "$SUSFS_REPO" "$WORK_DIR/susfs"
  git -C "$WORK_DIR/susfs" checkout -q "$SUSFS_REF"
  cp "$WORK_DIR/susfs/kernel_patches/fs/"* "$KDIR/fs/"
  cp "$WORK_DIR/susfs/kernel_patches/include/linux/"* "$KDIR/include/linux/"
  (cd "$KP/KernelSU" && patch -p1 --forward --no-backup-if-mismatch < "$WORK_DIR/susfs/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch") ||
    die "SUSFS 的 KernelSU 补丁打不上：请把 KSU_REF / SUSFS_REF 换成相互匹配的版本（SUSFS 跟随 KernelSU main 同步）"
  # 一加源码的 fs/proc/base.c 比 Google ACK 少一行 dma-buf.h 头文件，SUSFS 补丁以它为上下文，先补上
  grep -qxF '#include <linux/dma-buf.h>' "$KDIR/fs/proc/base.c" ||
    sed -i '/^#include <linux\/cpufreq_times.h>$/a #include <linux/dma-buf.h>' "$KDIR/fs/proc/base.c"
  (cd "$KDIR" && patch -p1 --forward --no-backup-if-mismatch < "$WORK_DIR/susfs/kernel_patches/50_add_susfs_in_gki-android14-6.1.patch") ||
    die "SUSFS 内核补丁打不上：一加源码与 SUSFS 版本有冲突，需要手动解决 .rej 文件"
  SUSFS_VERSION="$(sed -n 's/^#define SUSFS_VERSION "\(.*\)"/\1/p' "$KDIR/include/linux/susfs.h")"
  echo "SUSFS 版本: $SUSFS_VERSION"
fi

# ------------------------------------------------------------------ 5.5 优化 / 功能补丁
# 补丁来自社区仓库 WildKernels/kernel_patches（固定 commit，保证可复现）。
# 每个补丁都先 dry-run，打不上就跳过并警告，绝不中断——它们都是可选增强，不影响能否开机。
PATCHES_DIR=""
apply_patch() {  # $1=补丁相对路径  返回 0=成功 1=跳过
  local rel="$1" p="$PATCHES_DIR/$1"
  [ -f "$p" ] || { echo "  跳过（不存在）: $rel"; return 1; }
  if (cd "$KDIR" && patch -p1 --forward --fuzz=3 --no-backup-if-mismatch --dry-run < "$p" >/dev/null 2>&1); then
    (cd "$KDIR" && patch -p1 --forward --fuzz=3 --no-backup-if-mismatch < "$p" >/dev/null)
    echo "  已打: $rel"; return 0
  fi
  echo "  跳过（冲突，可能与官方源码版本不符）: $rel"; return 1
}

OPT_APPLIED=0 BBR3_OK=false NTSYNC_OK=false CONTAINERS_OK=false
if [ "$OPT" = true ] || [ "$BBR3" = true ] || [ "$NTSYNC" = true ] || [ "$CONTAINERS" = true ]; then
  log "拉取社区补丁 (kernel_patches @ ${PATCHES_REF:0:12})"
  PATCHES_DIR="$WORK_DIR/kernel_patches"
  rm -rf "$PATCHES_DIR"
  git clone -q "$PATCHES_REPO" "$PATCHES_DIR"
  git -C "$PATCHES_DIR" checkout -q "$PATCHES_REF"
fi

if [ "$OPT" = true ]; then
  log "应用社区调优补丁"
  # 经筛选：都能干净打上、在 arm64 上确实生效、适合日常使用。
  # 有意剔除：optimized_mem_operations（arm64 上是死代码，被 __HAVE_ARCH_* 屏蔽）、
  #           *_scaling_min_freq / use_unlikely_wrap_cpufreq（依赖一加私有 cpufreq 代码，打不上）。
  OPT_PATCHES=(
    common/reduce_cache_pressure.patch            # vfs_cache_pressure 100→50，多留 dentry/inode 缓存
    common/file_struct_8bytes_align.patch         # struct file 8 字节对齐
    common/increase_sk_mem_packets.patch          # socket 缓冲包数 256→1024
    common/disable_cache_hot_buddy.patch          # 关掉 CACHE_HOT_BUDDY，更契合 DynamIQ 大小核
    common/adjust_cpu_scan_order.patch            # 调整调度器扫核顺序
    common/f2fs_reduce_congestion.patch           # f2fs 拥塞等待 20ms→6ms
    common/reduce_gc_thread_sleep_time.patch      # f2fs GC 紧急休眠 500ms→50ms
    common/f2fs_enlarge_min_fsync_blocks.patch    # f2fs min_fsync_blocks 8→20
    common/increase_ext4_default_commit_age.patch # ext4 提交周期 5s→30s
    common/add_timeout_wakelocks_globally.patch   # 给 wakelock 加 500ms 超时，减少偷电
    common/minimise_wakeup_time.patch             # 收紧 alarmtimer 唤醒窗口
    common/avoid_extra_s2idle_wake_attempts.patch # 减少 s2idle 多余唤醒
    common/reduce_freeze_timeout.patch            # 冻结超时 20s→1s，息屏更快进深睡
    common/reduce_pci_pme_wakeups.patch           # PME 轮询 1s→4s
    common/silence_system_logspam.patch           # 过滤 healthd/logd 日志刷屏
    common/silence_irq_cpu_logspam.patch          # IRQ 亲和失败降为 debug 级
    common/mem_opt_prefetch.patch                 # arm64 memcpy 预取
    common/clear_page_16bytes_align.patch         # arm64 clear_page 对齐
    common/int_sqrt.patch                         # int_sqrt 优化
  )
  for p in "${OPT_PATCHES[@]}"; do apply_patch "${p%% *}" && OPT_APPLIED=$((OPT_APPLIED+1)); done
  # arm64 版 memcmp（WildKernels 对 >=5.16 内核直接套用）
  apply_patch common/optimise_memcmp.patch && OPT_APPLIED=$((OPT_APPLIED+1))
  echo "调优补丁已应用 $OPT_APPLIED 个"
fi

if [ "$BBR3" = true ]; then
  log "回合 BBRv3"
  apply_patch common/bbrv3/0001-net-tcp-backport-BBRv3-to-android14-6.1.patch && BBR3_OK=true
fi

if [ "$NTSYNC" = true ]; then
  log "应用 NTSync 补丁"
  if apply_patch common/ntsync/ntsync_compat_android14-6.1.patch &&
     apply_patch common/ntsync/ntsync_base.patch; then
    NTSYNC_OK=true
  fi
fi

if [ "$CONTAINERS" = true ]; then
  log "应用容器支持补丁"
  # 三个补丁缺一不可，任何一个打不上就整体放弃容器支持，绝不半开：
  #  - fix_sysvipc_kabi：SYSVIPC 会往 task_struct 加字段，这里改放进 Google 预留的 KABI 空位，保持接口不变
  #  - ghost-task：开了 PID 命名空间后，一加 oplus_bsp_midas 模块查不到进程会解空指针导致死机，
  #    只对这个模块返回一个占位进程
  #  - Guard-USER_NS：只允许 root 创建用户命名空间，普通应用拿不到，避免扩大攻击面
  if apply_patch common/droidspaces/fix_sysvipc_kabi_6_7_8.patch &&
     apply_patch common/droidspaces/0001-Return-ghost-task-if-task-is-null-and-is-requested-b.patch &&
     apply_patch common/droidspaces/0001-Guard-USER_NS-for-non-root-users.patch; then
    CONTAINERS_OK=true
  else
    die "容器支持补丁打不上（一加源码版本可能已变化），请关闭 CONTAINERS 或更新 PATCHES_REF"
  fi
fi

# ------------------------------------------------------------------ 6. 内核配置
# 自编译的内核签名密钥与官方不同，system_dlkm 里的 GKI 模块会被当作厂商模块加载；
# 保留受保护符号列表会导致 WiFi 等模块加载失败，必须删除（SUSFS 文档第 11 条）
rm -f "$KDIR"/android/abi_gki_protected_exports_*
# 去掉 uname 里的 git 哈希 / -dirty
sed -i 's/scm_version="$(scm_version --short)"/scm_version=""/' "$KDIR/scripts/setlocalversion"

MAKE_ARGS=("${MAKE_BASE[@]}" O="$KOUT")

log "生成配置 (gki_defconfig)"
rm -rf "$KOUT"
make "${MAKE_ARGS[@]}" gki_defconfig
cfg() { "$KDIR/scripts/config" --file "$KOUT/.config" "$@"; }

cfg --set-str LOCALVERSION "$LOCALVERSION_STR" -d LOCALVERSION_AUTO
set_lto "$KOUT/.config"
# KALLSYMS / KALLSYMS_ALL：KernelSU 和 APatch 都要靠它找内核符号（官方 GKI 本来就开着，这里确保不丢）
REQUIRED=(KALLSYMS KALLSYMS_ALL)
if [ "$KSU" = true ]; then cfg -e KSU; REQUIRED+=(KSU); fi
if [ "$SUSFS" = true ]; then cfg -e KSU_SUSFS; REQUIRED+=(KSU_SUSFS); fi
if [ "$BBR" = true ]; then
  cfg -e TCP_CONG_ADVANCED -e TCP_CONG_BBR
  REQUIRED+=(TCP_CONG_BBR)
fi
if [ "$BBR3_OK" = true ]; then
  cfg -e TCP_CONG_ADVANCED -e TCP_CONG_BBR3
  REQUIRED+=(TCP_CONG_BBR3)
fi
if [ "$BBR_DEFAULT" = true ]; then
  # 默认算法：装了 BBRv3 就用 bbr3，否则用 bbr（v1）
  if [ "$BBR3_OK" = true ]; then cfg --set-str DEFAULT_TCP_CONG bbr3
  elif [ "$BBR" = true ]; then cfg -e DEFAULT_BBR -d DEFAULT_CUBIC --set-str DEFAULT_TCP_CONG bbr; fi
fi
if [ "$NET_EXTRAS" = true ]; then
  cfg -e IP_NF_TARGET_TTL -e IP6_NF_TARGET_HL -e IP6_NF_MATCH_HL \
      -e IP_SET -e IP_SET_HASH_IP -e IP_SET_HASH_IPPORT \
      -e IP_SET_HASH_IPPORTIP -e IP_SET_HASH_NET -e IP_SET_HASH_NETPORT \
      -e IP_SET_HASH_NETIFACE -e IP_SET_BITMAP_PORT -e IP_SET_LIST_SET \
      -e NETFILTER_XT_SET -e NETFILTER_XT_MATCH_ADDRTYPE \
      -e IP6_NF_NAT -e IP6_NF_TARGET_MASQUERADE
  cfg --set-val IP_SET_MAX 65534   # 整数项，不能用 -e
  REQUIRED+=(IP_NF_TARGET_TTL IP6_NF_TARGET_HL IP_SET NETFILTER_XT_SET)
fi
if [ "$QDISC" = true ]; then
  cfg -e NET_SCH_FQ -e NET_SCH_FQ_CODEL -e NET_SCH_CAKE -e NET_SCH_PIE -e NET_SCH_FQ_PIE
  REQUIRED+=(NET_SCH_CAKE)
fi
if [ "$TMPFS_XATTR" = true ]; then
  cfg -e TMPFS_XATTR -e TMPFS_POSIX_ACL
  REQUIRED+=(TMPFS_XATTR)
fi
if [ "$NTSYNC_OK" = true ]; then
  cfg -e NTSYNC
  REQUIRED+=(NTSYNC)
fi
if [ "$CONTAINERS_OK" = true ]; then
  # 容器需要的命名空间与 IPC；IPC_NS 依赖 SYSVIPC/POSIX_MQUEUE，默认随之打开。
  # 网络（veth、bridge、NAT）、cgroup v2、overlayfs、seccomp 官方配置里已经有了。
  # 不开 CGROUP_PIDS / CGROUP_DEVICE / BRIDGE_NETFILTER / IP_VS：实测打开后 2880 个 KMI 符号 CRC 改变
  # （cgroup 子系统数组变大、skb 扩展编号整体后移、struct net 多出字段），厂商模块会全部加载失败。
  # Docker 在 cgroup v2 下用 BPF 管设备（CGROUP_BPF 已有），缺 BRIDGE_NETFILTER 只是告警，桥接网络仍可用。
  cfg -e SYSVIPC -e POSIX_MQUEUE -e IPC_NS -e PID_NS -e USER_NS -e DEVTMPFS \
      -e NETFILTER_XT_TARGET_REJECT -e NETFILTER_XT_TARGET_LOG -e NETFILTER_XT_MATCH_RECENT
  REQUIRED+=(SYSVIPC POSIX_MQUEUE IPC_NS PID_NS USER_NS DEVTMPFS)
fi
if [ "$O3" = true ]; then
  cfg -d CC_OPTIMIZE_FOR_PERFORMANCE -e CC_OPTIMIZE_FOR_PERFORMANCE_O3
fi
make "${MAKE_ARGS[@]}" olddefconfig

# olddefconfig 会静默丢弃依赖不满足的选项，这里逐项确认
for opt in "${REQUIRED[@]}"; do
  grep -q "^CONFIG_$opt=y" "$KOUT/.config" || die "CONFIG_$opt 未能启用，请检查依赖"
done

# ------------------------------------------------------------------ 7. 编译
log "开始编译（$JOBS 线程，LTO=$LTO）"
START=$(date +%s)
make "${MAKE_ARGS[@]}" -j"$JOBS" Image
KERNEL_RELEASE="$(cat "$KOUT/include/config/kernel.release")"
echo "编译完成，用时 $(( ($(date +%s) - START) / 60 )) 分钟，内核版本 $KERNEL_RELEASE"

ABI_RESULT="未检查（ABI_CHECK=false）"
if [ "$ABI_CHECK" = true ]; then
  log "KMI 检查：对比官方基线的符号 CRC"
  python3 "$SCRIPT_DIR/abi_check.py" "$KDIR" "$BASE_SYMVERS" "$KOUT/vmlinux.symvers" ||
    die "KMI 被破坏，刷进去厂商模块（WiFi、相机等）会加载失败，已停止出包。请关掉最近打开的功能再试"
  ABI_RESULT="通过（KMI 符号 CRC 与官方配置一致）"
fi

# ------------------------------------------------------------------ 8. 打包
log "打包"
rm -f "$OUT_DIR"/Image "$OUT_DIR"/*-AnyKernel3.zip "$OUT_DIR"/*-boot.img "$OUT_DIR"/build-info.txt
cp "$KOUT/arch/arm64/boot/Image" "$OUT_DIR/Image"
TAG="${KERNEL_NAME}-A${ANDROID_VER}-${KERNEL_VERSION}"
if [ "$KSU" = true ]; then TAG="$TAG-KSU"; else TAG="$TAG-Generic"; fi
[ "$SUSFS" = true ] && TAG="$TAG-SUSFS"
[ "$CONTAINERS_OK" = true ] && TAG="$TAG-Container"

AK3="$WORK_DIR/AnyKernel3"
rm -rf "$AK3"
git clone -q --depth=1 "$AK3_REPO" "$AK3"
rm -rf "$AK3/.git" "$AK3/.github" "$AK3/README.md"
cp "$SCRIPT_DIR/anykernel.sh" "$AK3/anykernel.sh"
sed -i "s|^kernel.string=.*|kernel.string=$TAG ($KERNEL_RELEASE)|" "$AK3/anykernel.sh"
cp "$OUT_DIR/Image" "$AK3/Image"
(cd "$AK3" && zip -qr9 "$OUT_DIR/$TAG-AnyKernel3.zip" . -x '*placeholder')

if [ -n "$STOCK_BOOT" ]; then
  # 用 Magisk 自带的 magiskboot 把新内核替换进官方 boot.img（ramdisk 在 init_boot，不受影响）
  [ -f "$STOCK_BOOT" ] || die "找不到 STOCK_BOOT=$STOCK_BOOT"
  MB="$WORK_DIR/magiskboot"
  if [ ! -x "$MB" ]; then
    MAGISK_TAG="$(git ls-remote --tags --refs https://github.com/topjohnwu/Magisk.git |
      awk -F/ '{print $3}' | grep -E '^v[0-9]+\.[0-9]+$' | sort -V | tail -n1)"
    curl -fsSL -o "$WORK_DIR/Magisk.apk" \
      "https://github.com/topjohnwu/Magisk/releases/download/$MAGISK_TAG/Magisk-$MAGISK_TAG.apk"
    python3 -c 'import sys, zipfile; open(sys.argv[2], "wb").write(zipfile.ZipFile(sys.argv[1]).read("lib/x86_64/libmagiskboot.so"))' \
      "$WORK_DIR/Magisk.apk" "$MB"
    chmod +x "$MB"
  fi
  REPACK="$WORK_DIR/repack"
  rm -rf "$REPACK" && mkdir -p "$REPACK"
  (
    cd "$REPACK"
    "$MB" unpack "$(realpath "$STOCK_BOOT")"
    cp "$OUT_DIR/Image" kernel
    "$MB" repack "$(realpath "$STOCK_BOOT")" "$OUT_DIR/$TAG-boot.img"
  )
fi

cat > "$OUT_DIR/build-info.txt" <<EOF
设备         : 一加平板 Pro (OnePlus Pad Pro, SM8650)
系统大版本   : Android $ANDROID_VER（清单 $MANIFEST）
内核分支     : $KERNEL_BRANCH @ $(git -C "$KDIR" rev-parse --short HEAD)
源码对应固件 : $(git -C "$KDIR" log -1 --format=%s)
内核版本     : $KERNEL_RELEASE
编译器       : $(clang --version | head -n1)
LTO / O3     : $LTO / $O3
KernelSU     : $([ "$KSU" = true ] && echo "$KSU_REF @ $(git -C "$KP/KernelSU" describe --tags --always)" || echo "未内置（通用内核，可用 APatch App 自行修补 boot.img，或配合 Magisk）")
SUSFS        : $([ "$SUSFS" = true ] && echo "$SUSFS_VERSION ($SUSFS_REF)" || echo 未集成)
BBR          : v1=$BBR v3=$BBR3_OK（默认算法: $BBR_DEFAULT）
网络扩展     : TTL/ipset=$NET_EXTRAS  队列调度=$QDISC
调优补丁     : $([ "$OPT" = true ] && echo "已应用 $OPT_APPLIED 个 (kernel_patches @ ${PATCHES_REF:0:12})" || echo 未应用)
NTSync       : $NTSYNC_OK
tmpfs xattr  : $TMPFS_XATTR
容器支持     : $CONTAINERS_OK
KMI 检查     : $ABI_RESULT
EOF
cat "$OUT_DIR/build-info.txt"
log "全部完成，产物在 $OUT_DIR"
ls -lh "$OUT_DIR"

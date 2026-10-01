# 一加平板 Pro 玩机内核编译方案

**简体中文** | [English](README.en.md)

适用机型：**一加平板 Pro（OnePlus Pad Pro，国行）**，海外版 OnePlus Pad 2 硬件相同但源码分支不同（`oneplus_pad2_*.xml`），不要混用。

---

## 0. 动手之前先弄清楚

| 项目 | 说明 |
| --- | --- |
| SoC | 骁龙 8 Gen 3，SM8650，平台代号 `pineapple` |
| 内核 | GKI 2.0，`android14-6.1`（系统升到 Android 15 / 16 内核仍是 6.1，目前官方源码为 6.1.118） |
| 分区 | 内核在 `boot`，ramdisk 在 `init_boot`，**刷内核只动 boot 分区** |
| 源码 | 一加官方开源：[OnePlusOSS/kernel_manifest](https://github.com/OnePlusOSS/kernel_manifest/tree/oneplus/sm8650) → [android_kernel_common_oneplus_sm8650](https://github.com/OnePlusOSS/android_kernel_common_oneplus_sm8650) |

**只想要 root 的话不需要编译内核**：KernelSU 管理器的 LKM 模式、Magisk、APatch 直接修补 `init_boot` 就行。
自己编内核的意义在于：内置 SUSFS 隐藏 root、BBR、网络扩展、自定义补丁，以及学习折腾。

**GKI 内核的边界**：CPU/GPU 频率表、温控、充电、屏幕等驱动都在厂商模块和设备树里（`vendor_boot` / `vendor_dlkm`），
只换 GKI 内核**做不到超频、改温控墙**。这类需求用 Scene / uperf 之类的用户态调度方案更现实。

**风险**：需要解锁 BL（会清空数据）；刷错会卡开机（按第 7 节可救回）；部分银行、支付类应用可能检测到解锁；OTA 前需要先还原官方 boot。

---

## 1. 三条路线

| 路线 | 适合谁 | 说明 |
| --- | --- | --- |
| A. 用社区成品 | 只想用，不想折腾编译 | [WildKernels/OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS) 有 `OP-PAD-PRO` 配置，Release 里下载对应系统版本的 AnyKernel3 包 |
| B. GitHub Actions 云编译 | 没有 Linux 电脑 | 用本仓库的工作流，网页上点一下，约半小时出包（4 核环境实测编译 13 分钟）；开着 KMI 检查时第一次要多编一个基线，约一小时 |
| C. 本地编译 | 想改源码、加补丁 | 运行本目录的 `build.sh` |

B 和 C 用的是同一个脚本，下面的内容对两者都适用。

---

## 2. 这个内核包含什么

| 功能 | 默认 | 说明 |
| --- | --- | --- |
| KernelSU（官方 tiann/KernelSU） | 开 | 内核级 root，内置，不再需要修补 init_boot。`KSU=false` 就是通用内核，可配合 APatch / Magisk，见下文 |
| SUSFS | 开 | 隐藏 root 痕迹（挂载、路径、uname、cmdline 等），配合 SUSFS 模块使用 |
| BBR + BBRv3 | 开（非默认算法） | 开机后 `sysctl -w net.ipv4.tcp_congestion_control=bbr3`；`BBR_DEFAULT=true` 可设为默认 |
| 队列调度 FQ/CAKE/PIE | 开 | 配合 BBR 用，降低网络延迟、缓解 bufferbloat |
| TTL / HL 修改、ipset（全套哈希类型）| 开 | 热点防检测、透明代理、防火墙类模块需要 |
| 社区调优补丁（20 个） | 开 | 内存/调度/文件系统/功耗微调，见下表；`OPT=false` 关闭 |
| NTSync | 关 | Wine/游戏兼容层同步原语；`NTSYNC=true` 开启 |
| tmpfs xattr / ACL | 开 | 部分模块和容器方案需要 |
| 容器支持 | 关 | `CONTAINERS=true`：LXC / Docker / Podman 需要的命名空间和 IPC，见下文 |
| KMI 检查 | 开 | 编译时核对内核接口，保证 WiFi、相机等厂商模块能正常加载，见下文 |
| ThinLTO | 开 | 可选 `none` / `thin` / `full` |
| O3 优化 | 关 | `O3=true` 用 -O3 编译（更激进，体积更大，未必更快） |
| 版本号伪装 | 开 | `uname -r` 形如 `6.1.118-android14-11`，编译用户/主机与官方一致（`kleaf@build-host`），不带 git 哈希 |
| 删除 `abi_gki_protected_exports` | 必做 | 自编内核签名密钥与官方不同，不删的话 WiFi 等模块会加载失败 |

### 社区调优补丁明细（`OPT=true`）

来自 [WildKernels/kernel_patches](https://github.com/WildKernels/kernel_patches)（固定 commit，可复现）。脚本会逐个 dry-run，打不上就跳过并警告，不中断。已剔除对本机无效或依赖一加私有代码的补丁（如 `optimized_mem_operations` 在 arm64 上是死代码，`*scaling_min_freq` 依赖一加 cpufreq）。

| 类别 | 补丁 | 作用 |
| --- | --- | --- |
| 内存/CPU | reduce_cache_pressure | `vfs_cache_pressure` 100→50，多留 dentry/inode 缓存 |
| | disable_cache_hot_buddy / adjust_cpu_scan_order | 调度器更契合大小核 DynamIQ |
| | mem_opt_prefetch / clear_page_16bytes_align / optimise_memcmp | arm64 汇编级内存操作优化 |
| | file_struct_8bytes_align / int_sqrt / increase_sk_mem_packets | 结构对齐、数学、socket 缓冲 |
| 文件系统 | f2fs_reduce_congestion / reduce_gc_thread_sleep_time / f2fs_enlarge_min_fsync_blocks | f2fs 读写与 GC 调优 |
| | increase_ext4_default_commit_age | ext4 提交周期 5s→30s |
| 功耗 | add_timeout_wakelocks_globally / minimise_wakeup_time | 减少偷电、收紧唤醒窗口 |
| | avoid_extra_s2idle_wake_attempts / reduce_freeze_timeout / reduce_pci_pme_wakeups | 息屏更快进深睡 |
| 杂项 | silence_system_logspam / silence_irq_cpu_logspam | 减少无用日志刷屏 |

这些都是数值微调和局部优化，社区在一加/骁龙设备上长期使用；提升偏“跟手感/续航”这类体感，不是跑分暴涨，介意稳定可 `OPT=false`。

### 通用内核（`KSU=false`）：配合 APatch / Magisk

关掉 KernelSU 后，内核不内置任何 root（SUSFS 依赖 KernelSU，会自动一起关掉），其他优化照旧。产物文件名带 `-Generic`。

- **APatch**：APatch 直接修补 `boot.img` 里的内核，内核需要 `KALLSYMS` 和 `KALLSYMS_ALL`，脚本会确认这两项开着。
  本项目**不在编译时预先打 APatch 补丁**：APatch 需要一个超级密钥（SuperKey），相当于 root 密码，公开的构建如果内置了它，等于所有人都知道。请在 APatch App 里用你自己的 SuperKey 修补本项目输出的 `boot.img`，再刷入，见第 6.5 节。
- **Magisk**：Magisk 修补的是 `init_boot`，和内核互不影响，刷入通用内核后原来的 Magisk 照常工作。
- **不要和 KernelSU 内核混用**：两套 root 同时存在会冲突。

### 容器支持（`CONTAINERS=true`）

打开后内核具备跑 LXC / Docker / Podman 的条件，容器有自己的进程树、IPC 和网络，可以用 systemd 当 1 号进程，速度接近原生。

| 打开的选项 | 用途 |
| --- | --- |
| `PID_NS` | 容器有独立的进程树，systemd 才能当 1 号进程 |
| `SYSVIPC` / `POSIX_MQUEUE` / `IPC_NS` | 进程间通信及其隔离，数据库、systemd 等依赖 |
| `USER_NS` | 用户命名空间（已限制为只有 root 能创建） |
| `DEVTMPFS` | 容器里自动生成 `/dev` 设备节点 |
| `NETFILTER_XT_TARGET_LOG` / `MATCH_RECENT` | 容器内 UFW、Fail2ban 等防火墙常用（REJECT 由官方已开的 `IP_NF_TARGET_REJECT` 提供） |

网络（veth、bridge、NAT）、cgroup v2、overlayfs、seccomp 官方内核本来就有。同时会打三个社区补丁，缺一不可，任何一个打不上就停止编译：

- **SYSVIPC 接口修补**：SYSVIPC 会往进程结构 `task_struct` 里加字段，补丁把它们放进 Google 预留的空位，保持接口不变。
- **oplus_bsp_midas 修补**：开了 PID 命名空间后，一加的这个功耗统计模块按 PID 查进程时会查不到，又不检查空指针，导致死机。补丁只对这个模块返回一个占位进程。属于绕过式修复，不改任何接口。
- **USER_NS 限制**：只允许 root 创建用户命名空间，普通应用拿不到，避免扩大攻击面。

**实测**：打开容器支持后 KMI 检查通过，全部 15243 个导出符号的 CRC 与官方一致。用 Docker 官方的 `check-config.sh` 检查，"基本必需"项从缺 6 个降到缺 3 个，剩下的 3 个是有意不开的：

| 没开的选项 | 为什么 | 对 Docker 的影响 |
| --- | --- | --- |
| `CGROUP_DEVICE`（以及可选的 `CGROUP_PIDS`） | 会改变 cgroup 结构的大小 | cgroup v2 下 Docker 改用 BPF 管设备（已支持）；只是不能限制容器进程数 |
| `BRIDGE_NETFILTER` | 会让网络包扩展的编号整体后移 | Docker 会告警，容器之间的流量不经过 iptables；默认桥接网络仍可用，有问题可改用 `--network host` |
| `NETFILTER_XT_MATCH_IPVS` | 依赖 `IP_VS`，会改变网络命名空间结构 | 只有 Swarm 集群模式需要 |

这几项是实测过的：一起打开后有 2880 个 KMI 符号的 CRC 改变，刷进去厂商模块会全部加载失败。

本项目的容器配置与 [Droidspaces](https://github.com/ravindu644/Droidspaces-OSS) 官方给 GKI 内核的清单一致，用的也是同一个 SYSVIPC 补丁。

#### 怎么启动容器

内核只提供能力，还需要一个用户态的容器工具。推荐 **Droidspaces**：专门为 Android 做的容器运行时，有图形界面，处理了 SELinux、网络等 Android 特有的问题，能跑带 systemd 的完整发行版。

1. **刷入带容器支持的内核**（`CONTAINERS=true`，产物名带 `-Container`），开机。
2. **处理 SUSFS**（默认内核带 SUSFS）：在 SuSFS4KSU 的设置里关闭「HIDE SUS MOUNTS FOR ALL PROCESSES」，否则容器起不来；或者编译时直接 `SUSFS=false`。Droidspaces 官方不支持和 SUSFS 一起用。
3. **安装 App**：从 [Droidspaces Releases](https://github.com/ravindu644/Droidspaces-OSS/releases/latest) 下载 APK 安装，授予 root。首次打开会自动把后端装到 `/data/local/Droidspaces/bin`。
   用 APatch 或 Magisk 的话，还要在 App 里开启「守护进程模式」并重启；KernelSU 不需要。
4. **自检**：设置（齿轮）→ 需求 → 检查需求，或在终端运行 `su -c droidspaces check`。必需项应该全绿，可选项有黄色警告不影响使用。
5. **装一个发行版**：容器页 → 「+」上方的云图标 → 选发行版（Debian、Ubuntu、Arch 等）→ 下载 → 安装。向导里推荐选「稀疏镜像」类型，在 f2fs 上更稳。
6. **启动和进入**：在容器卡片上点「启动」，然后到面板页点这个容器，用内置终端进入；或者复制登录命令到 Termux 里运行，形如 `su -c 'droidspaces --name=容器名 enter 用户名'`。

网络默认是「主机模式」，和平板共用网络，最省事；要隔离就选「NAT 模式」，还能配端口转发。图形桌面和 GPU 加速（Termux:X11 + Turnip）见 Droidspaces 的「显示、音频与桌面」文档。

也可以用 LXC 等其他工具，刷入后可在平板上运行 Docker 的 `check-config.sh` 或 `lxc-checkconfig` 自查（它们读 `/proc/config.gz`）。但 Termux 的 root 软件源里目前已经没有 docker 包，lxc 也停在很老的 3.1 版，在 Android 上自己搭比 Droidspaces 麻烦得多。

### KMI 检查（`ABI_CHECK=true`，默认开）

厂商模块（WiFi、相机、触控等）是按官方内核编译的，只认官方 GKI 导出的 KMI 符号及其校验值（CRC）。任何改动只要让其中一个符号的 CRC 变了，引用它的模块就会拒绝加载，症状是刷完 WiFi / 相机失灵。

开启后脚本会多编一个「官方源码 + 官方配置」的基线，编完正式内核后，把 KMI 清单（`abi_gki_aarch64` 加上 `_qcom`、`_oplus` 等全部附加清单，共 8000 多个符号）逐个比对 CRC，不一致就报错、不出包。基线按源码 commit 缓存，只有第一次编译会多花一倍时间。

已实测：默认配置（KernelSU + SUSFS + 调优补丁 + BBRv3 + 网络扩展）与官方基线相比，全部 15243 个导出符号的 CRC 都没变，只新增了 ipset 等 33 个符号。

注意：这项检查能发现接口签名的变化，但不能保证内核行为完全正确，真机测试仍然必要。

---

## 3. 系统版本与源码的对应关系

**必须按平板当前的系统大版本选择**，否则厂商模块可能加载失败（WiFi、相机、触控失灵）。

| 平板系统 | `ANDROID_VER` | 官方清单 | 内核分支 |
| --- | --- | --- | --- |
| ColorOS 14（Android 14） | `14` | `oneplus_pad_pro.xml` | `oneplus/sm8650_u_14.1.0_onepluspad_pro` |
| ColorOS 15（Android 15） | `15` | `oneplus_pad_pro_v.xml` | `oneplus/sm8650_v_15.0.0_pad_pro` |
| ColorOS 16（Android 16） | `16` | `oneplus_pad_pro_b.xml` | `oneplus/sm8650_b_16.0.0_pad_pro` |

脚本会自动从官方清单读取内核分支和一加锁定的 clang 版本（目前是 `clang-r487747c`）。
`build-info.txt` 里的「源码对应固件」（例如 `OPD2404_16.0.0.202(CN01)`）可以和平板「设置 → 关于本机」里的版本号对照，越接近越稳。

---

## 4. 路线 B：GitHub Actions 云编译

1. 把本仓库 fork 到自己账号（或直接在本仓库操作）。工作流文件 `.github/workflows/oneplus-pad-pro-kernel.yml` 需要在**默认分支**上，才会出现在 Actions 页面。
2. 打开 **Actions → 一加平板 Pro 玩机内核 → Run workflow**。
3. 选择系统版本和功能开关，点 **Run workflow**。
4. 完成后在该次运行页面底部的 **Artifacts** 下载产物。

可选参数 `stock_boot_url`：填一个**与平板当前系统版本完全一致**的官方 `boot.img` 直链（比如传到自己仓库的 Release），
就会额外输出一个可以直接 `fastboot flash` 的 `boot.img`。

---

## 5. 路线 C：本地编译

环境：Ubuntu 22.04 / 24.04（WSL2 也可以），建议 8 核 16 GB 内存，预留 30 GB 硬盘。

```bash
sudo apt update
sudo apt install -y git curl python3 make bc bison flex libssl-dev libelf-dev dwarves cpio zip ccache

cd oneplus-pad-pro-kernel
./build.sh                                   # 默认：Android 16 + KernelSU + SUSFS
ANDROID_VER=15 ./build.sh                    # 系统是 Android 15
SUSFS=false BBR_DEFAULT=true ./build.sh      # 不要 SUSFS，BBR 设为默认
STOCK_BOOT=~/boot.img ./build.sh             # 同时生成可 fastboot 刷入的 boot.img
```

全部参数：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ANDROID_VER` | `16` | 平板系统大版本：14 / 15 / 16 |
| `KSU` | `true` | 内置 KernelSU；`false` 为通用内核，可配合 APatch / Magisk |
| `KSU_REF` | `main` | KernelSU 分支 / tag / commit |
| `SUSFS` | `true` | 集成 SUSFS（需要 `KSU=true`） |
| `SUSFS_REF` | `gki-android14-6.1` | SUSFS 分支 / commit |
| `BBR` / `BBR3` | `true` / `true` | 编入 BBR / BBRv3 拥塞控制 |
| `BBR_DEFAULT` | `false` | 把默认 TCP 算法设为 bbr3（无则 bbr） |
| `NET_EXTRAS` | `true` | TTL/HL 修改、全套 ipset 哈希类型 |
| `QDISC` | `true` | FQ / FQ_CODEL / CAKE / PIE 队列调度 |
| `OPT` | `true` | 社区调优补丁（见第 2 节明细） |
| `NTSYNC` | `false` | NTSync 同步原语（Wine/游戏兼容层） |
| `TMPFS_XATTR` | `true` | tmpfs 的 xattr / POSIX ACL |
| `CONTAINERS` | `false` | 容器支持（LXC / Docker / Podman） |
| `ABI_CHECK` | `true` | 编基线核对 KMI 符号 CRC，不一致就不出包 |
| `O3` | `false` | 用 -O3 而非 -O2 编译 |
| `LTO` | `thin` | `none` / `thin` / `full` |
| `PATCHES_REF` | 固定 commit | WildKernels/kernel_patches 的 commit，可换新 |
| `LOCALVERSION_STR` | `-android14-11` | `uname -r` 中版本号之后的后缀 |
| `STOCK_BOOT` | 空 | 官方 boot.img 路径，用于生成可直接刷入的 boot.img |
| `CLANG_DIR` | 空 | 自备 clang 的 bin 目录，留空则下载一加同款 clang |
| `WORK_DIR` / `OUT_DIR` | `./work` / `./dist` | 源码与编译目录 / 产物目录 |

产物（`dist/`）：

- `Image`：内核镜像
- `*-AnyKernel3.zip`：卡刷包
- `*-boot.img`：仅在提供 `STOCK_BOOT` 时生成
- `build-info.txt`：本次编译的分支、版本、编译器等信息

想加自己的补丁：在 `build.sh` 第 6 步（内核配置）之前对 `$KDIR` 打补丁即可。

---

## 6. 刷入

### 6.1 准备

1. **解锁 BL**：开发者选项 → 打开「OEM 解锁」→ `adb reboot bootloader` → `fastboot flashing unlock`，在平板上确认。**会清空全部数据。**
2. **备份官方 boot.img**：下载与当前系统版本**完全一致**的全量包，用 [payload-dumper-go](https://github.com/ssut/payload-dumper-go) 从 `payload.bin` 提取 `boot.img`（顺便提取 `init_boot.img`）。救砖全靠它。
3. 如果之前用 Magisk 或 KernelSU LKM 修补过 `init_boot`，先刷回官方 `init_boot.img`，避免两套 root 冲突。

### 6.2 方式一：fastboot 刷 boot.img（首次推荐）

```bash
adb reboot bootloader
fastboot flash boot OPPadPro-GKI-A16-6.1.118-KSU-SUSFS-boot.img   # 刷入当前槽位
fastboot reboot
```

### 6.3 方式二：卡刷 AnyKernel3 包（已有 root 时）

用 [Kernel Flasher](https://github.com/capntrips/KernelFlasher) 或 Horizon Kernel Flasher 选择 `*-AnyKernel3.zip` 刷入后重启。
没有 root 可以先用 KernelSU 管理器的 LKM 模式临时获取 root，刷完内核后再刷回官方 `init_boot`。

### 6.4 开机后

1. 安装与内核中 KernelSU 版本匹配的 [KernelSU 管理器](https://github.com/tiann/KernelSU/releases)。
2. 需要隐藏 root 的话，在管理器里安装 SUSFS 模块（[susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu) 仓库中的 `ksu_module_susfs`，或社区维护的 susfs4ksu-module）。
3. `adb shell uname -a` 确认内核版本已变化。

### 6.5 通用内核配合 APatch

1. 编译时设 `KSU=false`，并提供与当前系统版本一致的官方 boot.img（本地用 `STOCK_BOOT`，云编译填 `stock_boot_url`），得到 `*-Generic-boot.img`。
2. 把它拷到平板，在 APatch App 里选择修补这个文件，设置你自己的 SuperKey（务必记住），得到修补后的镜像。
3. 拷回电脑：`fastboot flash boot <修补后的镜像>`，重启后在 APatch App 里输入 SuperKey。

APatch 的补丁就在内核里，所以**以后每次换内核都要重新修补**。用卡刷包更新内核会直接覆盖掉 APatch，重启后 root 就没了，建议 APatch 用户只用 boot.img 这条路。
配合 Magisk 则不受影响：通用内核用 6.2 或 6.3 的方式刷入即可，Magisk 在 `init_boot` 里，不用重新修补。

---

## 7. 救砖与升级

| 现象 | 处理 |
| --- | --- |
| 卡 logo / 反复重启 | 进 fastboot（关机后按住音量键 + 电源键，或 `adb reboot bootloader`），`fastboot flash boot 官方boot.img` |
| 能开机但 WiFi / 蓝牙 / 相机失灵 | 厂商模块没加载上：核对 `ANDROID_VER` 是否与系统一致；先刷回官方 boot |
| 想升级系统 | 先刷回官方 boot 再 OTA（或直接刷全量包）；升级后如果大版本变了，换对应清单重新编译 |

---

## 8. 进阶

- **换 root 方案**：[SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra)（带 KPM）或 [KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next)：把 `build.sh` 第 4 步（KernelSU）里的 `setup.sh` 地址换成对应项目的；它们集成 SUSFS 的方式与官方 KernelSU 不同，按各自文档调整 `build.sh` 第 5 步（SUSFS）。
- **为什么不用官方的 bazel 构建**：官方命令 `./kernel_platform/oplus/build/oplus_build_kernel.sh pineapple gki` 需要完整同步整个清单（含全部厂商模块和预编译工具，几十 GB）。只换 GKI 内核时，直接用 `make` 编译 `common` 就够了，社区项目也都这么做。
  注意一加的 `common` 里有几个软链接指向另一个仓库的 `vendor/oplus/kernel/*`（调度、锁优化、存储），缺了会在 Kconfig 阶段报 `can't open file "kernel/oplus_cpu/sched/Kconfig"`，脚本会自动只拉取这几个目录。
- **跟进官方更新**：一加更新源码后重新运行脚本即可，脚本每次都会重新读取官方清单。

---

## 9. 常见问题

**SUSFS 补丁打不上？**
SUSFS 会跟随官方 KernelSU `main` 分支同步（提交记录里的 “Sync with the official KernelSU main repo”）。两边都用最新版一般没问题；如果刚好赶上一边先更新，把 `SUSFS_REF` 指定到上一个 “Bump version” 提交，或把 `KSU_REF` 指定到对应的 tag。

**KernelSU 管理器提示版本不匹配？**
管理器版本要和内核里的 KernelSU 版本对应，`build-info.txt` 中记录了编译时用的 KernelSU 版本。

**报「KMI 被破坏」、不出包？**
说明某个改动让厂商模块要用的内核符号变了，刷进去 WiFi、相机等会失灵，所以脚本拒绝出包。日志里会列出变化的符号，关掉最近打开的功能（或换回默认的 `PATCHES_REF`）再编。不建议用 `ABI_CHECK=false` 硬绕过。

**`CONFIG_xxx 未能启用`？**
脚本会检查关键配置是否真的生效，报这个错说明该选项的依赖在当前源码里不满足，按提示去掉对应功能或补上依赖。

---

## 参考

- 官方源码：[OnePlusOSS/kernel_manifest](https://github.com/OnePlusOSS/kernel_manifest/tree/oneplus/sm8650)
- KernelSU：<https://kernelsu.org/zh_CN/guide/how-to-build.html>
- SUSFS：<https://gitlab.com/simonpunk/susfs4ksu/-/tree/gki-android14-6.1>
- AnyKernel3：<https://github.com/osm0sis/AnyKernel3>
- 社区成品与参考实现：[WildKernels/OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS)

# 一加平板 Pro 玩机内核编译方案

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

**风险**：需要解锁 BL（会清空数据）；刷错会卡开机（按第 6 节可救回）；部分银行、支付类应用可能检测到解锁；OTA 前需要先还原官方 boot。

---

## 1. 三条路线

| 路线 | 适合谁 | 说明 |
| --- | --- | --- |
| A. 用社区成品 | 只想用，不想折腾编译 | [WildKernels/OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS) 有 `OP-PAD-PRO` 配置，Release 里下载对应系统版本的 AnyKernel3 包 |
| B. GitHub Actions 云编译 | 没有 Linux 电脑 | 用本仓库的工作流，网页上点一下，约半小时出包（4 核环境实测编译 13 分钟） |
| C. 本地编译 | 想改源码、加补丁 | 运行本目录的 `build.sh` |

B 和 C 用的是同一个脚本，下面的内容对两者都适用。

---

## 2. 这个内核包含什么

| 功能 | 默认 | 说明 |
| --- | --- | --- |
| KernelSU（官方 tiann/KernelSU） | 开 | 内核级 root，内置，不再需要修补 init_boot |
| SUSFS | 开 | 隐藏 root 痕迹（挂载、路径、uname、cmdline 等），配合 SUSFS 模块使用 |
| BBR | 开（非默认算法） | `BBR_DEFAULT=true` 可设为默认，或开机后 `sysctl -w net.ipv4.tcp_congestion_control=bbr` |
| TTL / HL 修改、ipset | 开 | 热点防检测、透明代理、防火墙类模块需要 |
| ThinLTO | 开 | 可选 `none` / `thin` / `full` |
| 版本号伪装 | 开 | `uname -r` 形如 `6.1.118-android14-11`，编译用户/主机与官方一致（`kleaf@build-host`），不带 git 哈希 |
| 删除 `abi_gki_protected_exports` | 必做 | 自编内核签名密钥与官方不同，不删的话 WiFi 等模块会加载失败 |

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
| `KSU` | `true` | 集成 KernelSU |
| `KSU_REF` | `main` | KernelSU 分支 / tag / commit |
| `SUSFS` | `true` | 集成 SUSFS（需要 `KSU=true`） |
| `SUSFS_REF` | `gki-android14-6.1` | SUSFS 分支 / commit |
| `BBR` / `BBR_DEFAULT` | `true` / `false` | 编入 BBR / 设为默认 |
| `NET_EXTRAS` | `true` | TTL/HL 修改、ipset |
| `LTO` | `thin` | `none` / `thin` / `full` |
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

---

## 7. 救砖与升级

| 现象 | 处理 |
| --- | --- |
| 卡 logo / 反复重启 | 进 fastboot（关机后按住音量键 + 电源键，或 `adb reboot bootloader`），`fastboot flash boot 官方boot.img` |
| 能开机但 WiFi / 蓝牙 / 相机失灵 | 厂商模块没加载上：核对 `ANDROID_VER` 是否与系统一致；先刷回官方 boot |
| 想升级系统 | 先刷回官方 boot 再 OTA（或直接刷全量包）；升级后如果大版本变了，换对应清单重新编译 |

---

## 8. 进阶

- **换 root 方案**：[SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra)（带 KPM）或 [KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next)：把第 4 步的 `setup.sh` 地址换成对应项目的；它们集成 SUSFS 的方式与官方 KernelSU 不同，按各自文档调整第 5 步。
- **为什么不用官方的 bazel 构建**：官方命令 `./kernel_platform/oplus/build/oplus_build_kernel.sh pineapple gki` 需要完整同步整个清单（含全部厂商模块和预编译工具，几十 GB）。只换 GKI 内核时，直接用 `make` 编译 `common` 就够了，社区项目也都这么做。
  注意一加的 `common` 里有几个软链接指向另一个仓库的 `vendor/oplus/kernel/*`（调度、锁优化、存储），缺了会在 Kconfig 阶段报 `can't open file "kernel/oplus_cpu/sched/Kconfig"`，脚本会自动只拉取这几个目录。
- **跟进官方更新**：一加更新源码后重新运行脚本即可，脚本每次都会重新读取官方清单。

---

## 9. 常见问题

**SUSFS 补丁打不上？**
SUSFS 会跟随官方 KernelSU `main` 分支同步（提交记录里的 “Sync with the official KernelSU main repo”）。两边都用最新版一般没问题；如果刚好赶上一边先更新，把 `SUSFS_REF` 指定到上一个 “Bump version” 提交，或把 `KSU_REF` 指定到对应的 tag。

**KernelSU 管理器提示版本不匹配？**
管理器版本要和内核里的 KernelSU 版本对应，`build-info.txt` 中记录了编译时用的 KernelSU 版本。

**`CONFIG_xxx 未能启用`？**
脚本会检查关键配置是否真的生效，报这个错说明该选项的依赖在当前源码里不满足，按提示去掉对应功能或补上依赖。

---

## 参考

- 官方源码：[OnePlusOSS/kernel_manifest](https://github.com/OnePlusOSS/kernel_manifest/tree/oneplus/sm8650)
- KernelSU：<https://kernelsu.org/zh_CN/guide/how-to-build.html>
- SUSFS：<https://gitlab.com/simonpunk/susfs4ksu/-/tree/gki-android14-6.1>
- AnyKernel3：<https://github.com/osm0sis/AnyKernel3>
- 社区成品与参考实现：[WildKernels/OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS)

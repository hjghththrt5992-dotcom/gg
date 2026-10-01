# OnePlus Pad Pro Custom Kernel Build Guide

[简体中文](README.md) | **English**

Target device: **OnePlus Pad Pro (Chinese-market model, OPD2404)**. The global OnePlus Pad 2 has the same hardware but uses different source branches (`oneplus_pad2_*.xml`). Do not mix them.

---

## 0. Read this first

| Item | Details |
| --- | --- |
| SoC | Snapdragon 8 Gen 3, SM8650, platform codename `pineapple` |
| Kernel | GKI 2.0, `android14-6.1` (it stays 6.1 after upgrading to Android 15 / 16; the current official source is 6.1.118) |
| Partitions | The kernel lives in `boot` and the ramdisk in `init_boot`. **Flashing a kernel only touches the boot partition.** |
| Source | OnePlus's official open source: [OnePlusOSS/kernel_manifest](https://github.com/OnePlusOSS/kernel_manifest/tree/oneplus/sm8650) → [android_kernel_common_oneplus_sm8650](https://github.com/OnePlusOSS/android_kernel_common_oneplus_sm8650) |

**If you only want root, you don't need to build a kernel.** Patching `init_boot` with KernelSU (LKM mode), Magisk or APatch is enough.
Building your own kernel is worth it for built-in SUSFS root hiding, BBR, extra networking features, your own patches, and learning.

**Limits of a GKI kernel:** CPU/GPU frequency tables, thermal limits, charging and display drivers all live in vendor modules and the device tree (`vendor_boot` / `vendor_dlkm`).
Replacing only the GKI kernel **cannot overclock the device or change thermal limits**. For that, user-space tuning tools such as Scene or uperf are more realistic.

**Risks:** you must unlock the bootloader (this wipes all data); a bad flash can leave the device stuck at boot (recoverable, see Section 7); some banking and payment apps may detect the unlocked bootloader; you must restore the stock boot image before taking an OTA update.

---

## 1. Three ways to get a kernel

| Route | Best for | Notes |
| --- | --- | --- |
| A. Use a community build | You just want to use it, not build it | [WildKernels/OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS) has an `OP-PAD-PRO` config; download the AnyKernel3 zip for your OS version from its Releases |
| B. Build in the cloud with GitHub Actions | You don't have a Linux machine | Use this repository's workflow. One click on the web; a package is ready in about 30 minutes (the compile itself took 13 minutes on 4 cores) |
| C. Build locally | You want to change the source or add patches | Run `build.sh` in this directory |

B and C use the same script, so everything below applies to both.

---

## 2. What this kernel includes

| Feature | Default | Notes |
| --- | --- | --- |
| KernelSU (official tiann/KernelSU) | On | Kernel-level root, built in, no need to patch `init_boot` |
| SUSFS | On | Hides root traces (mounts, paths, uname, cmdline, etc.); use it together with the SUSFS module |
| BBR + BBRv3 | On (not the default algorithm) | After boot, run `sysctl -w net.ipv4.tcp_congestion_control=bbr3`; set `BBR_DEFAULT=true` to make it the default |
| FQ / CAKE / PIE queue disciplines | On | Pair with BBR to cut network latency and reduce bufferbloat |
| TTL / HL modification, ipset (all hash types) | On | Needed by hotspot-detection workarounds, transparent proxy and firewall modules |
| Community tuning patches (20) | On | Memory, scheduler, filesystem and power tweaks, see the table below; disable with `OPT=false` |
| NTSync | Off | Synchronization primitive for Wine / game compatibility layers; enable with `NTSYNC=true` |
| tmpfs xattr / ACL | On | Needed by some modules and container setups |
| ThinLTO | On | Options: `none` / `thin` / `full` |
| O3 optimization | Off | `O3=true` compiles with -O3 (more aggressive, larger, not necessarily faster) |
| Stock-looking version string | On | `uname -r` looks like `6.1.118-android14-11`, the build user/host match the official build (`kleaf@build-host`), and there is no git hash |
| Remove `abi_gki_protected_exports` | Required | A self-built kernel has a different signing key; without this, WiFi and other modules fail to load |

### Community tuning patches (`OPT=true`)

These come from [WildKernels/kernel_patches](https://github.com/WildKernels/kernel_patches) at a pinned commit, so builds are reproducible. The script dry-runs each patch and skips it with a warning if it doesn't apply, without stopping the build. Patches that do nothing on this device or depend on OnePlus's private code are excluded (for example, `optimized_mem_operations` is dead code on arm64, and the `*scaling_min_freq` patches depend on OnePlus's cpufreq code).

| Category | Patches | Effect |
| --- | --- | --- |
| Memory / CPU | reduce_cache_pressure | `vfs_cache_pressure` 100→50, keeps more dentry/inode cache |
| | disable_cache_hot_buddy / adjust_cpu_scan_order | Scheduler better suited to big.LITTLE (DynamIQ) |
| | mem_opt_prefetch / clear_page_16bytes_align / optimise_memcmp | arm64 assembly-level memory operation optimizations |
| | file_struct_8bytes_align / int_sqrt / increase_sk_mem_packets | Struct alignment, math, socket buffers |
| Filesystem | f2fs_reduce_congestion / reduce_gc_thread_sleep_time / f2fs_enlarge_min_fsync_blocks | f2fs I/O and GC tuning |
| | increase_ext4_default_commit_age | ext4 commit interval 5s→30s |
| Power | add_timeout_wakelocks_globally / minimise_wakeup_time | Less background battery drain, tighter wakeup windows |
| | avoid_extra_s2idle_wake_attempts / reduce_freeze_timeout / reduce_pci_pme_wakeups | Enters deep sleep faster with the screen off |
| Misc | silence_system_logspam / silence_irq_cpu_logspam | Less useless log spam |

These are small value tweaks and local optimizations that the community has used on OnePlus / Snapdragon devices for a long time. Expect better responsiveness and battery life rather than big benchmark gains. If you prefer maximum stability, use `OPT=false`.

---

## 3. Matching OS version to source

**You must choose based on the tablet's current major OS version.** Otherwise vendor modules may fail to load (WiFi, camera or touch stops working).

| Tablet OS | `ANDROID_VER` | Official manifest | Kernel branch |
| --- | --- | --- | --- |
| ColorOS 14 (Android 14) | `14` | `oneplus_pad_pro.xml` | `oneplus/sm8650_u_14.1.0_onepluspad_pro` |
| ColorOS 15 (Android 15) | `15` | `oneplus_pad_pro_v.xml` | `oneplus/sm8650_v_15.0.0_pad_pro` |
| ColorOS 16 (Android 16) | `16` | `oneplus_pad_pro_b.xml` | `oneplus/sm8650_b_16.0.0_pad_pro` |

The script reads the kernel branch and OnePlus's pinned clang version (currently `clang-r487747c`) from the official manifest automatically.
The "source firmware" line in `build-info.txt` (for example `OPD2404_16.0.0.202(CN01)`) can be compared with the build number in the tablet's Settings → About device. The closer they are, the safer.

---

## 4. Route B: cloud build with GitHub Actions

1. Fork this repository to your account (or use it directly). The workflow file `.github/workflows/oneplus-pad-pro-kernel.yml` must be on the **default branch** to show up on the Actions page.
2. Open **Actions → 一加平板 Pro 玩机内核 (OnePlus Pad Pro kernel) → Run workflow**.
3. Choose the OS version and feature toggles, then click **Run workflow**.
4. When it finishes, download the output from **Artifacts** at the bottom of the run page.

Optional input `stock_boot_url`: a direct link to the official `boot.img` that **exactly matches the tablet's current OS version** (for example, uploaded to a Release in your own repository).
With it, the workflow also outputs a `boot.img` you can flash directly with `fastboot flash`.

---

## 5. Route C: local build

Environment: Ubuntu 22.04 / 24.04 (WSL2 works too). 8 cores, 16 GB RAM and 30 GB of free disk are recommended.

```bash
sudo apt update
sudo apt install -y git curl python3 make bc bison flex libssl-dev libelf-dev dwarves cpio zip ccache

cd oneplus-pad-pro-kernel
./build.sh                                   # Default: Android 16 + KernelSU + SUSFS
ANDROID_VER=15 ./build.sh                    # Tablet is on Android 15
SUSFS=false BBR_DEFAULT=true ./build.sh      # No SUSFS, BBR as the default
STOCK_BOOT=~/boot.img ./build.sh             # Also produce a boot.img you can flash with fastboot
```

All options:

| Variable | Default | Description |
| --- | --- | --- |
| `ANDROID_VER` | `16` | Tablet's major OS version: 14 / 15 / 16 |
| `KSU` | `true` | Integrate KernelSU |
| `KSU_REF` | `main` | KernelSU branch / tag / commit |
| `SUSFS` | `true` | Integrate SUSFS (requires `KSU=true`) |
| `SUSFS_REF` | `gki-android14-6.1` | SUSFS branch / commit |
| `BBR` / `BBR3` | `true` / `true` | Build in BBR / BBRv3 congestion control |
| `BBR_DEFAULT` | `false` | Make bbr3 the default TCP algorithm (bbr if BBRv3 is not available) |
| `NET_EXTRAS` | `true` | TTL/HL modification, all ipset hash types |
| `QDISC` | `true` | FQ / FQ_CODEL / CAKE / PIE queue disciplines |
| `OPT` | `true` | Community tuning patches (see Section 2) |
| `NTSYNC` | `false` | NTSync synchronization primitive (Wine / game compatibility layers) |
| `TMPFS_XATTR` | `true` | tmpfs xattr / POSIX ACL |
| `O3` | `false` | Compile with -O3 instead of -O2 |
| `LTO` | `thin` | `none` / `thin` / `full` |
| `PATCHES_REF` | pinned commit | Commit of WildKernels/kernel_patches; can be updated |
| `LOCALVERSION_STR` | `-android14-11` | Suffix after the version number in `uname -r` |
| `STOCK_BOOT` | empty | Path to the official boot.img, used to produce a directly flashable boot.img |
| `CLANG_DIR` | empty | `bin` directory of your own clang; if empty, the same clang OnePlus uses is downloaded |
| `WORK_DIR` / `OUT_DIR` | `./work` / `./dist` | Source and build directory / output directory |

Output (`dist/`):

- `Image`: the kernel image
- `*-AnyKernel3.zip`: flashable zip
- `*-boot.img`: only produced when `STOCK_BOOT` is set
- `build-info.txt`: branch, versions, compiler and other details of this build

To add your own patches, apply them to `$KDIR` before step 6 (kernel configuration) in `build.sh`.

---

## 6. Flashing

### 6.1 Preparation

1. **Unlock the bootloader:** Developer options → enable "OEM unlocking" → `adb reboot bootloader` → `fastboot flashing unlock`, then confirm on the tablet. **This wipes all data.**
2. **Back up the official boot.img:** download the full OTA package that **exactly matches** your current OS version and extract `boot.img` (and `init_boot.img`) from `payload.bin` with [payload-dumper-go](https://github.com/ssut/payload-dumper-go). You need it to recover from a bad flash.
3. If you previously patched `init_boot` with Magisk or KernelSU LKM, flash the official `init_boot.img` back first so the two root solutions don't conflict.

### 6.2 Option 1: flash boot.img with fastboot (recommended for the first time)

```bash
adb reboot bootloader
fastboot flash boot OPPadPro-GKI-A16-6.1.118-KSU-SUSFS-boot.img   # Flashes the current slot
fastboot reboot
```

### 6.3 Option 2: flash the AnyKernel3 zip (if you already have root)

Use [Kernel Flasher](https://github.com/capntrips/KernelFlasher) or Horizon Kernel Flasher to flash `*-AnyKernel3.zip`, then reboot.
Without root, you can get temporary root with the KernelSU manager's LKM mode, flash the kernel, then flash the official `init_boot` back.

### 6.4 After booting

1. Install the [KernelSU manager](https://github.com/tiann/KernelSU/releases) that matches the KernelSU version in the kernel.
2. To hide root, install the SUSFS module in the manager (`ksu_module_susfs` from the [susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu) repository, or the community-maintained susfs4ksu-module).
3. Run `adb shell uname -a` to confirm the kernel version has changed.

---

## 7. Recovery and updates

| Symptom | Fix |
| --- | --- |
| Stuck at the logo / boot loop | Enter fastboot (hold a volume key + power with the device off, or `adb reboot bootloader`), then `fastboot flash boot <official boot.img>` |
| Boots, but WiFi / Bluetooth / camera doesn't work | Vendor modules failed to load: check that `ANDROID_VER` matches the OS; flash the official boot back first |
| Want to update the OS | Flash the official boot back before the OTA (or flash the full package directly); if the major version changed, rebuild with the matching manifest |

---

## 8. Advanced

- **Switching root solutions:** [SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra) (with KPM) or [KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next): replace the `setup.sh` URL in step 4 (KernelSU) of `build.sh` with the one from that project. They integrate SUSFS differently from official KernelSU, so adjust step 5 (SUSFS) of `build.sh` according to their docs.
- **Why not use the official bazel build:** the official command `./kernel_platform/oplus/build/oplus_build_kernel.sh pineapple gki` needs the entire manifest synced (all vendor modules and prebuilt tools, tens of GB). To replace only the GKI kernel, building `common` with `make` is enough, and community projects do the same.
  Note that OnePlus's `common` has a few symlinks into `vendor/oplus/kernel/*` (scheduler, locking, storage) in another repository. Without them, Kconfig fails with `can't open file "kernel/oplus_cpu/sched/Kconfig"`. The script fetches only those directories automatically.
- **Following official updates:** when OnePlus updates the source, just run the script again. It reads the official manifest on every run.

---

## 9. FAQ

**The SUSFS patch doesn't apply?**
SUSFS tracks the `main` branch of official KernelSU (see the "Sync with the official KernelSU main repo" commits). Using the latest of both usually works. If one side was updated before the other, set `SUSFS_REF` to the previous "Bump version" commit, or set `KSU_REF` to the matching tag.

**The KernelSU manager reports a version mismatch?**
The manager version must match the KernelSU version in the kernel. `build-info.txt` records the KernelSU version used for the build.

**`CONFIG_xxx 未能启用` (CONFIG_xxx could not be enabled)?**
The script checks that key options actually took effect. This error means the option's dependencies aren't met in the current source. Follow the message to drop that feature or add the missing dependency.

---

## References

- Official source: [OnePlusOSS/kernel_manifest](https://github.com/OnePlusOSS/kernel_manifest/tree/oneplus/sm8650)
- KernelSU: <https://kernelsu.org/guide/how-to-build.html>
- SUSFS: <https://gitlab.com/simonpunk/susfs4ksu/-/tree/gki-android14-6.1>
- AnyKernel3: <https://github.com/osm0sis/AnyKernel3>
- Community builds and reference implementation: [WildKernels/OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS)

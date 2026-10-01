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
| B. Build in the cloud with GitHub Actions | You don't have a Linux machine | Use this repository's workflow. One click on the web; a package is ready in about 30 minutes (on 4 cores the compile took 13 minutes without PGO and 21 minutes for the first build with PGO); with the KMI check on, the first run also builds a baseline and takes about an hour |
| C. Build locally | You want to change the source or add patches | Run `build.sh` in this directory |

B and C use the same script, so everything below applies to both.

---

## 2. What this kernel includes

| Feature | Default | Notes |
| --- | --- | --- |
| KernelSU (official tiann/KernelSU) | On | Kernel-level root, built in, no need to patch `init_boot`. With `KSU=false` you get a generic kernel for APatch / Magisk, see below |
| SUSFS | On | Hides root traces (mounts, paths, uname, cmdline, etc.); use it together with the SUSFS module |
| BBR + BBRv3 | On (not the default algorithm) | After boot, run `sysctl -w net.ipv4.tcp_congestion_control=bbr3`; set `BBR_DEFAULT=true` to make it the default |
| FQ / CAKE / PIE queue disciplines | On | Pair with BBR to cut network latency and reduce bufferbloat |
| TTL / HL modification, ipset (all hash types) | On | Needed by hotspot-detection workarounds, transparent proxy and firewall modules |
| Community tuning patches (20) | On | Memory, scheduler, filesystem and power tweaks, see the table below; disable with `OPT=false` |
| NTSync | Off | Synchronization primitive for Wine / game compatibility layers; enable with `NTSYNC=true` |
| tmpfs xattr / ACL | On | Needed by some modules and container setups |
| Container / Linux desktop support | On | Run full Linux distributions and a graphical desktop with Droidspaces and similar tools, see below; turn off with `CONTAINERS=false` |
| KMI check | On | Verifies the kernel interface at build time so WiFi, camera and other vendor modules still load, see below |
| PGO | On | Optimizes the build with OnePlus's real-device profiling data from the source; hot code is grouped together, making it faster and more power-efficient, see below |
| ThinLTO | On | Options: `none` / `thin` / `full` (full with PGO needs more than 16 GB of memory) |
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

### Generic kernel (`KSU=false`): for APatch / Magisk

With KernelSU off, the kernel has no built-in root (SUSFS depends on KernelSU and is turned off automatically); all other optimizations stay. Output file names contain `-Generic`.

- **APatch:** APatch patches the kernel inside `boot.img` directly and needs `KALLSYMS` and `KALLSYMS_ALL`; the script confirms both are on.
  This project **does not pre-apply APatch at build time.** APatch needs a SuperKey, which is effectively your root password; a public build with a built-in SuperKey would mean everyone knows it. Patch the `boot.img` from this project in the APatch app with your own SuperKey, then flash it (see Section 6.5).
- **Magisk:** Magisk patches `init_boot`, which is independent of the kernel, so an existing Magisk install keeps working after flashing the generic kernel.
- **Don't combine with the KernelSU kernel:** two root solutions at once will conflict.

### Container / Linux desktop support (`CONTAINERS=true`, on by default)

With this on, the kernel can run LXC / Docker / Podman. Containers get their own process tree, IPC and network, can use systemd as PID 1, and run at near-native speed.

| Option enabled | Purpose |
| --- | --- |
| `PID_NS` | A separate process tree per container, needed for systemd as PID 1 |
| `SYSVIPC` / `POSIX_MQUEUE` / `IPC_NS` | Inter-process communication and its isolation; databases, systemd and others depend on it |
| `USER_NS` | User namespaces (restricted so that only root can create them) |
| `DEVTMPFS` | `/dev` device nodes are created automatically inside containers |
| `NETFILTER_XT_TARGET_LOG` / `MATCH_RECENT` | Used by firewalls such as UFW and Fail2ban inside containers (REJECT comes from `IP_NF_TARGET_REJECT`, already on in the official config) |

Networking (veth, bridge, NAT), cgroup v2, overlayfs and seccomp are already in the official kernel. Three community patches are also applied. All three are required; if any of them fails to apply, the build stops:

- **SYSVIPC interface fix:** SYSVIPC adds fields to the process structure `task_struct`; the patch places them in slots Google reserved for this, so the interface stays unchanged.
- **oplus_bsp_midas fix:** with PID namespaces enabled, this OnePlus power-statistics module fails to find processes by PID and doesn't check for a null pointer, which crashes the kernel. The patch returns a placeholder process only to this module. It is a workaround and changes no interface.
- **USER_NS restriction:** only root may create user namespaces, so regular apps can't use them and the attack surface doesn't grow.

**Tested:** with container support on, the KMI check passes and all 15,243 exported symbols keep the same CRC as the official build. Docker's official `check-config.sh` goes from 6 missing "generally necessary" items down to 3, and those 3 are left off on purpose:

| Option left off | Why | Impact on Docker |
| --- | --- | --- |
| `CGROUP_DEVICE` (and the optional `CGROUP_PIDS`) | Changes the size of cgroup structures | Under cgroup v2 Docker uses BPF for device control (already supported); you just can't limit a container's process count |
| `BRIDGE_NETFILTER` | Shifts the numbering of all network packet extensions | Docker shows a warning and traffic between containers bypasses iptables; the default bridge network still works, use `--network host` if you hit problems |
| `NETFILTER_XT_MATCH_IPVS` | Depends on `IP_VS`, which changes the network namespace structure | Only needed for Swarm cluster mode |

These were tested: turning them on together changed the CRC of 2,880 KMI symbols, which would make every vendor module fail to load.

This project's container config matches the list [Droidspaces](https://github.com/ravindu644/Droidspaces-OSS) gives for GKI kernels, and uses the same SYSVIPC patch.

#### Starting a container

The kernel only provides the capability; you still need a user-space container tool. **Droidspaces** is recommended: a container runtime built for Android with a GUI that handles Android-specific issues such as SELinux and networking, and can run full distributions with systemd.

1. **Flash this project's kernel** (container support is on by default; the output name contains `-Container`) and boot.
2. **Deal with SUSFS** (the default kernel includes it): turn off "HIDE SUS MOUNTS FOR ALL PROCESSES" in the SuSFS4KSU settings, or containers fail to start; or build with `SUSFS=false`. Droidspaces does not officially support running alongside SUSFS.
3. **Install the app:** download the APK from [Droidspaces Releases](https://github.com/ravindu644/Droidspaces-OSS/releases/latest), install it and grant root. On first launch it installs its backend to `/data/local/Droidspaces/bin` automatically.
   With APatch or Magisk, also enable "Daemon mode" in the app and reboot; KernelSU doesn't need this.
4. **Self-check:** Settings (gear) → Requirements → Check Requirements, or run `su -c droidspaces check` in a terminal. Required items should all be green; yellow warnings for optional items are fine.
5. **Install a distribution:** Containers tab → cloud icon above "+" → pick a distribution (Debian, Ubuntu, Arch, etc.) → Download → Install. In the wizard, the "sparse image" type is recommended for better stability on f2fs.
6. **Start and enter it:** tap "Start" on the container card, then open the container in the Panel tab and use the built-in terminal; or copy the login command into Termux, which looks like `su -c 'droidspaces --name=<container> enter <user>'`.

Networking defaults to "host mode", sharing the tablet's network, which is the simplest; choose "NAT mode" for isolation and port forwarding.

#### Recommended: a development environment in the browser (code-server)

No X11 and no extra apps: run code-server (VS Code in the browser) in the container and open it in the tablet's browser to get a full editor, terminal and extension marketplace, with touch, keyboard and copy/paste all working.

1. Start a container as described above (Debian / Ubuntu is easiest) and keep the default **host mode** networking.
2. Run the one-step script in the container terminal (as root; the user name is optional and defaults to root):
   `curl -fsSL https://raw.githubusercontent.com/hjghththrt5992-dotcom/gg/main/oneplus-pad-pro-kernel/container/setup-code-server.sh | bash -s -- <user>`
3. The script prints the address and password at the end. Open `http://127.0.0.1:8080` in the tablet's browser and enter the password.
4. In the Chrome menu choose "Add to Home screen" or "Install app" to open it full screen like a standalone app.

What the script does: installs code-server with its official install script (the official deb / rpm package on Debian / Ubuntu / Fedora, the official standalone build elsewhere); writes a config that **listens only on 127.0.0.1** (other devices on the same Wi-Fi can't connect) with a random password and file permissions 600; enables it with systemd so it starts whenever the container starts. Change the port with an environment variable such as `PORT=8090`; an existing config is never overwritten.

The full flow was tested on Ubuntu 24.04: installation, config generation, redirect to the login page when not logged in, rejection of a wrong password, access to the editor with the right password, listening only on 127.0.0.1, and refusal of access from another address. Not tested on the device (arm64 container); code-server provides official arm64 packages.

Note: the script downloads from GitHub, which may need a proxy on some networks. If the container uses NAT mode, 127.0.0.1 is no longer shared with Android; switch back to host mode.

#### Graphical desktop (X11, optional)

On the kernel side, **container support is all you need**; no extra options. Checked item by item against the Droidspaces `check` source: namespaces, devtmpfs, loop, ext4, overlayfs, FUSE, TUN, veth, bridge, cgroup v2, and the SysV IPC used by X11 shared memory are all present in the container build. Display goes through the Termux:X11 app, and GPU acceleration goes through the Turnip driver using the tablet's existing Adreno driver.

1. Install **Termux** and **Termux:X11**, then run the Droidspaces setup script once in Termux (installs the display and audio components):
   `curl -fsSL https://github.com/ravindu644/Droidspaces-OSS/raw/refs/heads/dev/scripts/setup-termux.sh | bash`
2. Search for **XFCE** in the Droidspaces distribution repository and install the official XFCE build (it starts the desktop automatically).
3. In the container config, enable "Configure Termux:X11" (and "Configure PulseAudio" for sound), start the container, and open Termux:X11 to see the desktop. This step uses software rendering.
4. **GPU acceleration** (Adreno 750 is supported by [Mesa for Android Container](https://github.com/lfdevs/mesa-for-android-container)): install its package for your distribution inside the container, extract it to `/` and run `ldconfig`; in the container config enable "GPU Access", **turn off "VirGL"**, and add the environment variables `MESA_LOADER_DRIVER_OVERRIDE=kgsl` and `TU_DEBUG=noconform`. `glxinfo -B` showing Turnip / Adreno 750 means it works.
5. Rendering on the 3K screen is demanding; if it lags, lower the resolution or use scaling in the Termux:X11 settings.

See the Droidspaces "Display, audio and desktop" documentation for details. Droidspaces' community device list has no Snapdragon 8 Gen 3 device yet, and this project hasn't verified this flow on a real device either.

Other tools such as LXC also work; after flashing you can run Docker's `check-config.sh` or `lxc-checkconfig` on the tablet to verify (they read `/proc/config.gz`). However, the Termux root repository no longer has a docker package and its lxc is stuck at the old 3.1, so setting things up yourself on Android is much harder than with Droidspaces.

### PGO (`PGO=true`, on by default): optimizing with real-device data

OnePlus ships real-device profiling data in the source, `pgo-profiles/vmlinux_v1.profdata` (IR instrumentation, 51,398 functions). The hottest paths are timer reads, zram compression (swap / LZ4), Binder, CPU frequency scaling and SELinux lookups, exactly the tablet's everyday workload. OnePlus also changed the build rules: with `ARCH_SUPPORTS_PGO_CLANG` on, this data applies to every file (a few directories are excluded by OnePlus's rules) and the cross-module inlining limit goes from 5 to 60. The open-source build scripts don't enable it, so it's unknown whether OnePlus's official build uses it.

With it, the compiler groups hot code together and moves cold code away, so the CPU instruction cache hits more often and the same work runs with fewer instructions and cache misses: faster and more power-efficient.

Tested (thin LTO):
- The compiled bitcode really carries real-device call counts (for example 30 functions in `mm/swapfile.o`), while `mm/kasan`, excluded by OnePlus's rules, has none, as a control
- After linking, 1,613 hot sections sit within 0.9 MB and 33,000 cold sections (6.7 MB) are moved aside
- The KMI check passes and there are no stack frame size warnings; peak memory 9.2 GB, first build 21 minutes; `Image` grows by about 0.8 MB (more inlining)

**Why full LTO isn't the default:** OnePlus's own build script labels full LTO as "better performance", but in testing full LTO + PGO exceeded 14 GB of memory during linking and was killed; a 16 GB GitHub machine can't run it either. So the default is thin LTO + PGO. On a machine with enough memory you can try `LTO=full` yourself.

**What else can save power:** CPU frequency policy, the scheduler (Qualcomm WALT, OnePlus scheduling tweaks), thermal limits and the GPU all live in vendor modules that a GKI kernel can't change. What the kernel can do (compiler optimization, the tuning patches above, MGLRU memory reclaim which the official config already enables) is essentially done. For more power savings, use the system's power-saving mode or user-space tuning tools such as Scene or uperf to adjust frequency scaling and core allocation.

### KMI check (`ABI_CHECK=true`, on by default)

Vendor modules (WiFi, camera, touch, etc.) are built against the official kernel and only accept the KMI symbols exported by the official GKI, with their checksums (CRCs). If any change alters the CRC of one of those symbols, modules that use it refuse to load, and WiFi or the camera stops working after flashing.

With this on, the script also builds a baseline from the official source and official config. After building the real kernel, it compares the CRC of every symbol in the KMI lists (`abi_gki_aarch64` plus all additional lists such as `_qcom` and `_oplus`, over 8,000 symbols). Any mismatch is an error and no package is produced. The baseline is cached per source commit, so only the first build takes about twice as long.

Tested: compared with the official baseline, the default configuration (KernelSU + SUSFS + tuning patches + BBRv3 + networking extras) keeps the CRC of all 15,243 exported symbols unchanged and only adds 33 new ones (ipset and similar); with PGO added, the KMI check passes as well.

Note: this check catches interface signature changes but cannot prove the kernel behaves correctly; testing on the device is still necessary.

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
| `KSU` | `true` | Built-in KernelSU; `false` gives a generic kernel for APatch / Magisk |
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
| `CONTAINERS` | `true` | Container / Linux desktop support (Droidspaces, LXC, Docker) |
| `ABI_CHECK` | `true` | Build a baseline and compare KMI symbol CRCs; no package on mismatch |
| `O3` | `false` | Compile with -O3 instead of -O2 |
| `PGO` | `true` | Optimize the build with OnePlus's real-device profiling data (`pgo-profiles/`) |
| `LTO` | `thin` | `none` / `thin` / `full` (full with PGO needs more than 16 GB of memory) |
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

### 6.5 Generic kernel with APatch

1. Build with `KSU=false` and provide the official boot.img matching your current OS version (`STOCK_BOOT` locally, `stock_boot_url` in the cloud) to get `*-Generic-boot.img`.
2. Copy it to the tablet, patch it in the APatch app, and set your own SuperKey (remember it).
3. Copy the patched image back to your computer: `fastboot flash boot <patched image>`, reboot, then enter the SuperKey in the APatch app.

APatch lives inside the kernel, so **you must re-patch every time you change kernels.** Updating the kernel with the flashable zip overwrites APatch and you lose root after rebooting, so APatch users should stick to the boot.img route.
Magisk is unaffected: flash the generic kernel as in 6.2 or 6.3; Magisk lives in `init_boot` and doesn't need re-patching.

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

**The build reports "KMI 被破坏" (KMI broken) and produces no package?**
Some change altered kernel symbols that vendor modules use; flashing it would break WiFi, the camera and so on, so the script refuses to package it. The log lists the changed symbols. Turn off the feature you enabled most recently (or go back to the default `PATCHES_REF`) and rebuild. Bypassing it with `ABI_CHECK=false` is not recommended.

**`CONFIG_xxx 未能启用` (CONFIG_xxx could not be enabled)?**
The script checks that key options actually took effect. This error means the option's dependencies aren't met in the current source. Follow the message to drop that feature or add the missing dependency.

---

## References

- Official source: [OnePlusOSS/kernel_manifest](https://github.com/OnePlusOSS/kernel_manifest/tree/oneplus/sm8650)
- KernelSU: <https://kernelsu.org/guide/how-to-build.html>
- SUSFS: <https://gitlab.com/simonpunk/susfs4ksu/-/tree/gki-android14-6.1>
- AnyKernel3: <https://github.com/osm0sis/AnyKernel3>
- Community builds and reference implementation: [WildKernels/OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS)

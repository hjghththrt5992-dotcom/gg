# OnePlus Pad Pro Custom Kernel

[简体中文](README.md) | **English**

A GKI kernel build for the OnePlus Pad Pro (Snapdragon 8 Gen 3 / SM8650).
It builds from OnePlus's official open-source code, integrates KernelSU, SUSFS, BBR / BBRv3 and a set of community tuning patches,
and outputs an AnyKernel3 flashable zip, plus an optional `boot.img` you can flash directly with fastboot.

- Full guide, flashing and recovery: [`oneplus-pad-pro-kernel/README.en.md`](oneplus-pad-pro-kernel/README.en.md)
- Local build: `oneplus-pad-pro-kernel/build.sh`
- Cloud build: Actions → 一加平板 Pro 玩机内核 (OnePlus Pad Pro kernel) → Run workflow

## License

The scripts and documentation in this repository are licensed under [AGPL-3.0](LICENSE).
The kernel source, KernelSU, SUSFS and the patches keep their own original licenses (mostly GPL-2.0).

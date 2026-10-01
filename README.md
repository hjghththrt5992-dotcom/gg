# 一加平板 Pro 玩机内核

一加平板 Pro（OnePlus Pad Pro，骁龙 8 Gen 3 / SM8650）的 GKI 内核编译方案：
基于一加官方开源源码，集成 KernelSU、SUSFS、BBR / BBRv3 和一组社区调优补丁，
输出 AnyKernel3 卡刷包，可选输出能直接 fastboot 刷入的 `boot.img`。

- 完整方案、刷入和救砖说明：[`oneplus-pad-pro-kernel/README.md`](oneplus-pad-pro-kernel/README.md)
- 本地编译：`oneplus-pad-pro-kernel/build.sh`
- 云编译：Actions → 「一加平板 Pro 玩机内核」→ Run workflow

## 许可证

本仓库的脚本和文档采用 [AGPL-3.0](LICENSE)。
内核源码、KernelSU、SUSFS 及各补丁沿用各自原有的许可证（主要是 GPL-2.0）。

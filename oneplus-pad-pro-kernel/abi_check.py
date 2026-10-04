#!/usr/bin/env python3
"""对比两次编译的导出符号校验值（CRC），检查改动有没有破坏 KMI。

厂商模块（WiFi、相机、触控等）是针对官方内核编译的，官方 GKI 内核只导出
KMI 清单里的符号，所以厂商模块只会用到这些符号。内核开着 MODVERSIONS，
符号的 CRC 一旦和官方不一致，引用它的模块就会拒绝加载。

用法：abi_check.py <内核 common 目录> <基线 vmlinux.symvers> <新 vmlinux.symvers>
退出码：0 = 没有破坏，1 = 有 KMI 符号丢失或 CRC 变化
"""
import pathlib
import sys


def load_kmi(common: pathlib.Path) -> set[str]:
    # KMI = abi_gki_aarch64 加上 BUILD.bazel 里的全部附加清单（_qcom、_oplus 等）
    symbols = set()
    for path in sorted((common / "android").glob("abi_gki_aarch64*")):
        if path.suffix in (".stg", ".allowed_breaks"):
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith(("[", "#")):
                symbols.add(line)
    return symbols


def load_symvers(path: pathlib.Path) -> dict[str, tuple[str, str]]:
    # 每行：0xCRC<TAB>符号<TAB>vmlinux<TAB>EXPORT_SYMBOL[_GPL]<TAB>命名空间
    table = {}
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) >= 4:
            table[fields[1]] = (fields[0], fields[3])
    return table


def main() -> int:
    common, base_path, new_path = map(pathlib.Path, sys.argv[1:4])
    kmi = load_kmi(common)
    base = load_symvers(base_path)
    new = load_symvers(new_path)

    checked = kmi & base.keys()
    missing = sorted(s for s in checked if s not in new)
    changed = sorted(s for s in checked if s in new and new[s][0] != base[s][0])
    to_gpl = sorted(s for s in checked if s in new
                    and base[s][1] == "EXPORT_SYMBOL" and new[s][1] == "EXPORT_SYMBOL_GPL")

    print(f"KMI 清单 {len(kmi)} 个符号，基线中导出 {len(checked)} 个，逐个比对 CRC")
    for title, items in (("丢失", missing), ("CRC 变化", changed), ("变成 GPL-only", to_gpl)):
        if items:
            print(f"  {title} {len(items)} 个：")
            for s in items[:40]:
                print(f"    {s}")
            if len(items) > 40:
                print(f"    ……另有 {len(items) - 40} 个")

    if missing or changed:
        print("KMI 被破坏：厂商模块会因为符号版本不匹配而加载失败")
        return 1
    if to_gpl:
        print("警告：有符号变成了 GPL-only，非 GPL 的厂商模块可能加载失败")
    print("KMI 未被破坏")
    return 0


if __name__ == "__main__":
    sys.exit(main())

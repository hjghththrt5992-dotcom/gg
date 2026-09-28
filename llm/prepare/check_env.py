"""检测电脑配置，测一下算力，推荐合适的模型大小并估算训练时间。"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time

from common import physical_cores, pick_device
from config import save_settings

# LoRA 微调每个 token 的计算量（GFLOP，含前向、反向和梯度检查点重算）
TRAIN_GFLOP_PER_TOKEN = {"0.5b": 2.0, "1.5b": 7.0}
TOKENS_PER_1000_SAMPLES = 1.1e6


def cpu_name() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        if system == "Darwin":
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            m = re.search(r"model name\s*:\s*(.+)", f.read())
            if m:
                return m.group(1).strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or "未知"


def ram_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().total / 1024 ** 3
    except ImportError:
        return 0.0


def gpu_info() -> tuple[str, float] | None:
    """返回 (显卡名称, 显存GB)。"""
    try:
        import torch

        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return p.name, p.total_memory / 1024 ** 3
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "Apple 芯片（MPS，与内存共享）", ram_gb() * 0.6
    except ImportError:
        pass
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total",
                                           "--format=csv,noheader,nounits"], text=True, timeout=10)
            name, mem = out.strip().splitlines()[0].rsplit(",", 1)
            return name.strip() + "（PyTorch 未启用 CUDA，见 README）", float(mem) / 1024
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return None


def benchmark_gflops(seconds: float = 3.0) -> float:
    """用矩阵乘法粗测 CPU/GPU 算力。"""
    import torch

    device, _ = pick_device()
    dtype = torch.float32 if device == "cpu" else torch.float16
    a = torch.randn(1024, 1024, device=device, dtype=dtype)
    b = torch.randn(1024, 1024, device=device, dtype=dtype)
    n, t0 = 0, time.time()
    while time.time() - t0 < seconds:
        (a @ b).sum().item()
        n += 1
    return 2 * 1024 ** 3 * n / (time.time() - t0) / 1e9


def check() -> dict:
    cores, logical = physical_cores(), os.cpu_count()
    ram = ram_gb()
    gpu = gpu_info()
    print("==== 电脑配置 ====")
    print(f"  系统    {platform.system()} {platform.release()}  Python {platform.python_version()}")
    print(f"  CPU     {cpu_name()}（{cores} 核 {logical} 线程）")
    print(f"  内存    {ram:.1f} GB")
    print(f"  显卡    {f'{gpu[0]}，显存 {gpu[1]:.1f} GB' if gpu else '无可用 NVIDIA 显卡（将使用 CPU）'}")
    try:
        import torch

        print(f"  PyTorch {torch.__version__}，CPU 指令集 {torch.backends.cpu.get_cpu_capability()}")
    except ImportError:
        print("  [!] 还没有安装 PyTorch，请先 pip install -r llm/requirements.txt")
        return {}

    print("\n正在测算力（约 3 秒）…")
    gflops = benchmark_gflops()
    print(f"  矩阵运算速度约 {gflops:.0f} GFLOPS")

    has_gpu = bool(gpu) and "未启用" not in gpu[0]
    if has_gpu and gpu[1] >= 6:
        size, train_size = "1.5b", "1.5b"
    elif ram >= 12:
        size, train_size = "1.5b", "0.5b"
    else:
        size, train_size = "0.5b", "0.5b"

    print("\n==== 推荐 ====")
    print(f"  问答模型：Qwen2.5-{size.upper()}-Instruct")
    print(f"  微调模型：Qwen2.5-{train_size.upper()}-Instruct")
    print("  预估 LoRA 微调耗时（每 1000 条训练样本，1 轮）：")
    for s, gflop in TRAIN_GFLOP_PER_TOKEN.items():
        hours = TOKENS_PER_1000_SAMPLES * gflop / (gflops * 0.5) / 3600
        print(f"    {s.upper()}：约 {hours:.1f} 小时" + ("  ← 推荐" if s == train_size else ""))
    if ram < 8:
        print("  [!] 内存小于 8GB，建议安装 llama-cpp-python 并使用 GGUF 量化模型（download --gguf）")
    save_settings(size=size, train_size=train_size)
    print("\n已保存推荐设置，之后的命令默认使用上述模型。")
    return {"size": size, "train_size": train_size, "gflops": gflops}

"""检测电脑配置，测一下算力，推荐合适的底座模型大小并估算训练时间。"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time

from common import physical_cores, pick_device
from config import save_settings

# LoRA 训练每个 token 的计算量（GFLOP）≈ 非嵌入参数量 × 6（前向 2 + 反向 2 + 梯度检查点重算 2），
# 整段文字样本还要对每个位置算词表输出层，约再加 0.5~1 GFLOP。
# 按实测校准：4 核 CPU 测速 470~580 GFLOPS 时，问答样本 0.5B 约 150 token/秒，1.5B 约 44 token/秒
TRAIN_GFLOP_PER_TOKEN = {"0.5b": 2.6, "1.5b": 7.8}
TRAIN_EFFICIENCY = 0.55  # 训练时的有效算力约为下面矩阵乘法测速结果的 55%（略偏保守）


def estimate_hours(tokens: float, size: str, gflops: float) -> float:
    """训练 tokens 个词元大约需要多少小时。"""
    return tokens * TRAIN_GFLOP_PER_TOKEN[size] / (gflops * TRAIN_EFFICIENCY) / 3600


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
    """用和模型里形状相近的矩阵乘法测算力。"""
    import torch

    device, dtype = pick_device()
    m, k, n = 1024, 896, 4864  # 1024 个 token × 0.5B 模型前馈层的权重
    a = torch.randn(m, k, device=device, dtype=dtype)
    b = torch.randn(k, n, device=device, dtype=dtype)

    def sync():
        if device == "cuda":
            torch.cuda.synchronize()
        elif device == "mps":
            torch.mps.synchronize()

    for _ in range(3):  # 预热
        a @ b
    sync()
    count, t0 = 0, time.time()
    while time.time() - t0 < seconds:
        for _ in range(10):
            a @ b
        sync()
        count += 10
    return 2 * m * k * n * count / (time.time() - t0) / 1e9


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

    hours = {s: estimate_hours(1e6, s, gflops) for s in TRAIN_GFLOP_PER_TOKEN}
    has_gpu = bool(gpu) and "未启用" not in gpu[0]
    # 1.5B 训练需要约 12GB 内存（或 8GB 显存），并且 100 万词元能在一晚上（8 小时）内训练完才推荐
    big_enough = (has_gpu and gpu[1] >= 8) or (not has_gpu and ram >= 14)
    size = "1.5b" if big_enough and hours["1.5b"] <= 8 else "0.5b"

    print("\n==== 推荐 ====")
    print(f"  底座模型：Qwen2.5-{size.upper()}-Instruct")
    print("  预估训练耗时（每 100 万词元，约相当于 10 万字的知识库训练 3 轮）：")
    for s, h in hours.items():
        print(f"    {s.upper()}：约 {h:.1f} 小时" + ("  ← 推荐" if s == size else ""))
    if ram < 8:
        print("  [!] 内存小于 8GB，只能训练 0.5B；建议安装 llama-cpp-python 并运行 download --gguf 加快生成训练数据")
    save_settings(size=size, gflops=round(gflops))
    print("\n已保存推荐设置，之后的命令默认使用上述模型。")
    return {"size": size, "gflops": gflops}

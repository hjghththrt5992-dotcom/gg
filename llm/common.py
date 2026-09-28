"""公用工具：设备选择、线程设置、JSONL 读写。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from config import ROOT


def physical_cores() -> int:
    try:
        import psutil

        return psutil.cpu_count(logical=False) or os.cpu_count() or 4
    except ImportError:
        return os.cpu_count() or 4


def pick_device():
    """返回 (device, dtype)：有 NVIDIA 显卡用显卡，苹果芯片用 mps，否则用 CPU。"""
    import torch

    torch.set_num_threads(physical_cores())
    if torch.cuda.is_available():
        device = "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    if device == "cuda":
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    elif device == "mps":
        dtype = torch.float16
    else:
        dtype = torch.float32
    return device, dtype


def portable_path(path: Path) -> str:
    """项目内的路径存为相对路径，整个项目文件夹挪位置也能用。"""
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(Path(path).resolve())


def resolve_path(stored: str) -> Path:
    return ROOT / stored  # stored 是绝对路径时，拼接结果就是它本身


def read_jsonl(path: Path) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def write_jsonl(path: Path, items: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            n += 1
    return n


def dtype_kwargs(dtype) -> dict:
    """from_pretrained 的精度参数：新版 transformers 叫 dtype，旧版叫 torch_dtype。"""
    import transformers

    major, minor = (int(x) for x in transformers.__version__.split(".")[:2])
    return {"dtype": dtype} if (major, minor) >= (4, 56) else {"torch_dtype": dtype}


def render_chat(tokenizer, messages: list[dict], add_generation_prompt: bool) -> str:
    # enable_thinking=False：对 Qwen3 这类带"思考模式"的模型关闭思考，其他模型会忽略此参数
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=add_generation_prompt,
                                         enable_thinking=False)

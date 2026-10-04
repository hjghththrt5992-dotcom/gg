"""可选：把 LoRA 合并进底座模型，得到一个完整的新模型，便于分发或转成 GGUF 用 llama.cpp 高速运行。"""
from __future__ import annotations

from pathlib import Path

from common import dtype_kwargs
from config import LORA_DIR, OUTPUT_DIR
from serve.backends import adapter_base

GGUF_GUIDE = """
[下一步] 转成 GGUF 4bit 量化模型（可选，推理速度约提升 2~4 倍，内存占用降到约 1/4）：
  1. 下载 llama.cpp：git clone https://github.com/ggml-org/llama.cpp
     （Windows 可在 https://github.com/ggml-org/llama.cpp/releases 下载编译好的程序）
  2. pip install -r llama.cpp/requirements.txt
  3. python llama.cpp/convert_hf_to_gguf.py {merged} --outfile {f16} --outtype f16
  4. llama-quantize {f16} {q4} Q4_K_M
  5. python llm/main.py chat --model {q4}
"""


def merge_lora(adapter_dir: Path = LORA_DIR, out_dir: Path = OUTPUT_DIR / "merged") -> Path:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    base = adapter_base(adapter_dir)
    print(f"[合并] 底座 {base} + LoRA {adapter_dir}")
    model = AutoModelForCausalLM.from_pretrained(str(base), **dtype_kwargs(torch.float32))
    model = PeftModel.from_pretrained(model, str(adapter_dir)).merge_and_unload()
    model.to(torch.bfloat16).save_pretrained(str(out_dir))
    AutoTokenizer.from_pretrained(str(base)).save_pretrained(str(out_dir))
    print(f"[合并] 完成，保存在 {out_dir}")
    print(GGUF_GUIDE.format(merged=out_dir, f16=out_dir.parent / "merged-f16.gguf",
                            q4=out_dir.parent / "merged-q4_k_m.gguf"))
    return out_dir

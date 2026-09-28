"""模型推理后端：
- llama.cpp（GGUF 4bit 量化）：最快、最省内存，老电脑首选，需要 pip install llama-cpp-python
- transformers：无需额外安装，可直接加载 LoRA 微调结果
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from typing import Iterator

from common import dtype_kwargs, physical_cores, pick_device, render_chat, resolve_path
from config import GGUF_MODELS, LLM_MODELS, MAX_NEW_TOKENS, OUTPUT_DIR, REPETITION_PENALTY, model_dir


class HFBackend:
    name = "transformers"

    def __init__(self, model_path: Path, adapter: Path | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.device, dtype = pick_device()
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        model = AutoModelForCausalLM.from_pretrained(str(model_path), **dtype_kwargs(dtype))
        if adapter is not None:
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
        self.model = model.to(self.device).eval()
        self.torch = torch
        self.label = f"{Path(model_path).name}" + (f" + LoRA({Path(adapter).name})" if adapter else "")

    def stream(self, messages: list[dict], max_new_tokens: int = MAX_NEW_TOKENS) -> Iterator[str]:
        from transformers import TextIteratorStreamer

        prompt = render_chat(self.tokenizer, messages, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to(self.device)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=max_new_tokens,
            do_sample=False,  # 知识问答用贪心解码，结果稳定
            temperature=None, top_p=None, top_k=None,
            repetition_penalty=REPETITION_PENALTY,
            pad_token_id=self.tokenizer.eos_token_id if self.tokenizer.pad_token_id is None
            else self.tokenizer.pad_token_id,
        )
        thread = Thread(target=self._generate, kwargs=kwargs, daemon=True)
        thread.start()
        yield from streamer
        thread.join()

    def _generate(self, **kwargs):
        with self.torch.inference_mode():
            self.model.generate(**kwargs)


class LlamaCppBackend:
    name = "llama.cpp"

    def __init__(self, gguf_path: Path, n_ctx: int = 4096):
        from llama_cpp import Llama

        self.llm = Llama(model_path=str(gguf_path), n_ctx=n_ctx, n_threads=physical_cores(),
                         n_gpu_layers=-1, verbose=False)
        self.label = Path(gguf_path).name

    def stream(self, messages: list[dict], max_new_tokens: int = MAX_NEW_TOKENS) -> Iterator[str]:
        for part in self.llm.create_chat_completion(messages=messages, stream=True, max_tokens=max_new_tokens,
                                                    temperature=0.0, repeat_penalty=REPETITION_PENALTY):
            delta = part["choices"][0]["delta"].get("content")
            if delta:
                yield delta


def _has_llama_cpp() -> bool:
    try:
        import llama_cpp  # noqa: F401

        return True
    except ImportError:
        return False


def adapter_base(adapter: Path) -> Path:
    """LoRA 目录里记录了训练时用的底座模型。"""
    info = json.loads((adapter / "train_info.json").read_text(encoding="utf-8"))
    return resolve_path(info["base_model"])


def load_backend(size: str, backend: str = "auto", model: str | None = None, adapter: str | None = None,
                 finetuned: bool = False):
    """按优先级选择模型：--model 指定路径 > 微调结果 > GGUF 量化模型 > 原版模型。"""
    if finetuned and adapter is None:
        adapter = str(OUTPUT_DIR / "lora")
    if adapter:
        adapter_path = Path(adapter)
        if not (adapter_path / "adapter_config.json").exists():
            raise SystemExit(f"找不到 LoRA 微调结果：{adapter_path}，请先运行 train")
        base = Path(model) if model else adapter_base(adapter_path)
        return HFBackend(base, adapter_path)
    if model:
        path = Path(model)
        if path.suffix == ".gguf":
            return LlamaCppBackend(path)
        return HFBackend(path)

    repo, filename = GGUF_MODELS[size]
    gguf = model_dir(repo) / filename
    hf_dir = model_dir(LLM_MODELS[size])
    if backend in ("auto", "gguf") and gguf.exists() and _has_llama_cpp():
        return LlamaCppBackend(gguf)
    if backend == "gguf":
        raise SystemExit("GGUF 模式需要：pip install llama-cpp-python，并运行 download --gguf")
    if (hf_dir / "config.json").exists():
        return HFBackend(hf_dir)
    raise SystemExit(f"还没有下载 {size} 模型，请先运行：python llm/main.py download --size {size}")

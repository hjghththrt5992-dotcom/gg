"""文本向量模型（默认 bge-small-zh-v1.5，CLS 池化 + 归一化）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from common import pick_device
from config import BGE_QUERY_INSTRUCTION


class Embedder:
    def __init__(self, model_dir: Path, query_instruction: str = BGE_QUERY_INSTRUCTION):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.device, _ = pick_device()
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        self.model = AutoModel.from_pretrained(str(model_dir)).to(self.device).eval()
        self.query_instruction = query_instruction
        self.name = Path(model_dir).name

    @property
    def dim(self) -> int:
        return self.model.config.hidden_size

    def encode(self, texts: list[str], is_query: bool = False, batch_size: int = 32,
               max_length: int = 512, progress: bool = False) -> np.ndarray:
        if is_query:
            texts = [self.query_instruction + t for t in texts]
        out = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            enc = self.tokenizer(batch, padding=True, truncation=True, max_length=max_length,
                                 return_tensors="pt").to(self.device)
            with self.torch.inference_mode():
                hidden = self.model(**enc).last_hidden_state[:, 0]
                hidden = self.torch.nn.functional.normalize(hidden.float(), dim=-1)
            out.append(hidden.cpu().numpy())
            if progress:
                print(f"\r  向量化 {min(start + batch_size, len(texts))}/{len(texts)}", end="", flush=True)
        if progress:
            print()
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.concatenate(out).astype(np.float32)

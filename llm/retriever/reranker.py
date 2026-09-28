"""交叉编码器重排（bge-reranker）：把问题和资料一起送进模型打分，比向量相似度更准，但更慢。"""
from __future__ import annotations

from pathlib import Path

from common import pick_device


class Reranker:
    def __init__(self, model_dir: Path):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.device, _ = pick_device()
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(model_dir)).to(self.device).eval()

    def score(self, query: str, passages: list[str], batch_size: int = 16) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(passages), batch_size):
            batch = passages[start:start + batch_size]
            enc = self.tokenizer([query] * len(batch), batch, padding=True, truncation=True,
                                 max_length=512, return_tensors="pt").to(self.device)
            with self.torch.inference_mode():
                logits = self.model(**enc).logits.view(-1).float()
            scores.extend(logits.cpu().tolist())
        return scores

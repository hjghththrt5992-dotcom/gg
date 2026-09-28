"""混合检索：BM25 关键词 + 向量语义，RRF 融合，可选交叉编码器重排。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from common import read_jsonl, resolve_path
from config import CANDIDATES, INDEX_DIR, RERANK_MODEL, RRF_K, TOP_K, model_dir
from kb_builder.bm25 import BM25
from kb_builder.chunker import embed_text


class Retriever:
    def __init__(self, index_dir: Path = INDEX_DIR, use_rerank: bool = False, embed_dir: Path | None = None,
                 verbose: bool = True):
        if not (index_dir / "chunks.jsonl").exists():
            raise SystemExit("还没有知识库索引，请先运行：python llm/main.py build")
        self.chunks = read_jsonl(index_dir / "chunks.jsonl")
        self.bm25 = BM25.load(index_dir / "bm25.json.gz")
        meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))

        self.vectors = self.embedder = None
        vec_path = index_dir / "embeddings.npy"
        if vec_path.exists() and meta.get("embed_dir"):
            embed_dir = embed_dir or resolve_path(meta["embed_dir"])  # 必须和建索引时用同一个向量模型
            if (embed_dir / "config.json").exists():
                from kb_builder.embedder import Embedder

                self.vectors = np.load(vec_path)
                self.embedder = Embedder(embed_dir)
        self.reranker = None
        if use_rerank:
            rdir = model_dir(RERANK_MODEL)
            if (rdir / "config.json").exists():
                from retriever.reranker import Reranker

                self.reranker = Reranker(rdir)
            elif verbose:
                print("[提示] 未下载重排模型，跳过重排。可运行：python llm/main.py download --rerank")
        if verbose:
            mode = "关键词+向量" if self.embedder else "仅关键词"
            print(f"[知识库] {meta['docs']} 篇文档 / {meta['chunks']} 块，检索模式：{mode}"
                  + ("+重排" if self.reranker else ""))

    def search(self, query: str, top_k: int = TOP_K, candidates: int = CANDIDATES) -> list[dict]:
        ranked_lists = [[i for i, _ in self.bm25.search(query, candidates)]]
        if self.embedder is not None:
            q = self.embedder.encode([query], is_query=True)[0]
            sims = self.vectors @ q
            top = np.argsort(-sims)[:candidates]
            ranked_lists.append([int(i) for i in top])

        fused: dict[int, float] = {}
        for ranked in ranked_lists:
            for rank, i in enumerate(ranked):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank + 1)
        order = sorted(fused, key=lambda i: -fused[i])[:candidates]

        hits = [dict(self.chunks[i], score=fused[i]) for i in order]
        if self.reranker is not None and hits:
            scores = self.reranker.score(query, [embed_text(h) for h in hits])
            for h, s in zip(hits, scores):
                h["score"] = float(s)
            hits.sort(key=lambda h: -h["score"])
        return hits[:top_k]

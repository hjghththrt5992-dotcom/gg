"""构建知识库索引：切分 → BM25 → 向量。向量有缓存，文档没变的块不会重复计算。"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from common import portable_path, read_jsonl, write_jsonl
from config import EMBED_MODEL, INDEX_DIR, KB_DOCS, model_dir
from kb_builder.bm25 import BM25
from kb_builder.chunker import chunk_document, embed_text
from kb_builder.loaders import load_documents


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _load_cache(index_dir: Path, embed_name: str) -> dict[str, np.ndarray]:
    """读取上次构建的向量，按文本哈希索引。"""
    try:
        meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))
        if meta.get("embed_model") != embed_name:
            return {}
        old_chunks = read_jsonl(index_dir / "chunks.jsonl")
        old_vecs = np.load(index_dir / "embeddings.npy")
    except (OSError, ValueError, KeyError):
        return {}
    if len(old_chunks) != len(old_vecs):
        return {}
    return {c["hash"]: v for c, v in zip(old_chunks, old_vecs)}


def build_index(docs_dir: Path = KB_DOCS, index_dir: Path = INDEX_DIR, use_embed: bool = True,
                embed_dir: Path | None = None) -> dict:
    t0 = time.time()
    index_dir.mkdir(parents=True, exist_ok=True)
    docs = load_documents(docs_dir)
    if not docs:
        raise SystemExit(f"没有在 {docs_dir} 找到可用文档（支持 md/txt/html/pdf/docx）")
    chunks = [c for d in docs for c in chunk_document(d)]
    texts = [embed_text(c) for c in chunks]
    for c, t in zip(chunks, texts):
        c["hash"] = _hash(t)
    print(f"  文档 {len(docs)} 篇，切分为 {len(chunks)} 块")

    embed_dir = embed_dir or model_dir(EMBED_MODEL)
    embed_name = None
    vec_path = index_dir / "embeddings.npy"
    if use_embed and (embed_dir / "config.json").exists():
        from kb_builder.embedder import Embedder

        embed_name = embed_dir.name
        cache = _load_cache(index_dir, embed_name)
        todo = [i for i, c in enumerate(chunks) if c["hash"] not in cache]
        print(f"  向量：复用 {len(chunks) - len(todo)} 块，新计算 {len(todo)} 块")
        embedder = Embedder(embed_dir)
        new_vecs = embedder.encode([texts[i] for i in todo], progress=True)
        for i, v in zip(todo, new_vecs):
            cache[chunks[i]["hash"]] = v
        np.save(vec_path, np.stack([cache[c["hash"]] for c in chunks]).astype(np.float32))
    else:
        if use_embed:
            print("  [提示] 未找到向量模型，仅建立关键词索引。运行 download 下载后重新 build 效果更好。")
        vec_path.unlink(missing_ok=True)

    BM25().fit(texts).save(index_dir / "bm25.json.gz")
    write_jsonl(index_dir / "chunks.jsonl", chunks)
    meta = {
        "docs": len(docs),
        "chunks": len(chunks),
        "embed_model": embed_name,
        "embed_dir": portable_path(embed_dir) if embed_name else None,
        "docs_dir": str(docs_dir),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (index_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  完成，用时 {time.time() - t0:.1f} 秒，索引保存在 {index_dir}")
    return meta

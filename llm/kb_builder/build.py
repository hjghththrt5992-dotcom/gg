"""第 1 步：读取知识库文档，切成段落，作为后面生成训练数据的原料。"""
from __future__ import annotations

import time
from pathlib import Path

from common import write_jsonl
from config import KB_DOCS, PASSAGES
from kb_builder.chunker import chunk_document
from kb_builder.loaders import load_documents


def build_passages(docs_dir: Path = KB_DOCS, out_path: Path = PASSAGES) -> list[dict]:
    t0 = time.time()
    docs = load_documents(docs_dir)
    if not docs:
        raise SystemExit(f"没有在 {docs_dir} 找到可用文档（支持 md/txt/html/pdf/docx）")
    passages = [c for d in docs for c in chunk_document(d)]
    write_jsonl(out_path, passages)
    chars = sum(len(p["text"]) for p in passages)
    print(f"  文档 {len(docs)} 篇，切分为 {len(passages)} 段，共 {chars / 10000:.1f} 万字")
    print(f"  完成，用时 {time.time() - t0:.1f} 秒，保存在 {out_path}")
    return passages

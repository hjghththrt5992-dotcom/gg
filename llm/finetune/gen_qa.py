"""第 1 步：让模型根据知识库每一段资料出题，自动生成问答对。

生成的问答会经过过滤：答案必须能在原文中找到依据（字的二元组重合率），问题不能引用"本文""资料"等。
支持断点续跑：已经处理过的资料块会跳过。
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from common import read_jsonl
from config import INDEX_DIR, OUTPUT_DIR
from kb_builder.chunker import chunk_header

QA_PROMPT = (
    "请根据下面的资料，出 {n} 道能直接从资料中找到答案的问答题。\n"
    "要求：\n"
    "1. 问题要具体、完整，单独拿出来也能看懂，不要出现“资料”“文中”“上文”“本文”等字眼；\n"
    "2. 答案用一到三句话，内容完全来自资料；\n"
    "3. 严格按以下格式输出，不要输出其他内容：\n"
    "问：……\n答：……\n\n"
    "资料：\n{context}"
)
BAD_QUESTION = re.compile(r"资料|文中|上文|本文|这段|该段|原文|以上|下列")
LEADING_REF = re.compile(r"^(根据|按照|依据)(以上|上述|这段)?(资料|材料|上文|原文|文中)(所述|内容)?[，,：:]?\s*")
QA_PATTERN = re.compile(r"问[:：]\s*(.+?)\s*\n+\s*答[:：]\s*(.+?)(?=\n\s*问[:：]|\Z)", re.S)


def bigrams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def grounding(answer: str, context: str) -> float:
    """答案中有多大比例的二元组出现在原文里。"""
    a = bigrams(re.sub(r"\[\d+\]", "", answer))
    return len(a & bigrams(context)) / max(1, len(a))


def parse_qa(output: str) -> list[tuple[str, str]]:
    # 小模型常写"根据资料，……？"，去掉这种开头，保留问题本身
    return [(LEADING_REF.sub("", q.strip()), a.strip()) for q, a in QA_PATTERN.findall(output)]


def filter_qa(pairs: list[tuple[str, str]], context: str, min_grounding: float) -> list[tuple[str, str]]:
    kept = []
    for q, a in pairs:
        if not (5 <= len(q) <= 80 and 2 <= len(a) <= 300):
            continue
        if BAD_QUESTION.search(q) or grounding(a, context) < min_grounding:
            continue
        kept.append((q, a))
    return kept


def generate_qa(backend, out_path: Path = OUTPUT_DIR / "qa.jsonl", per_chunk: int = 2, limit: int | None = None,
                min_grounding: float = 0.6, min_chunk_chars: int = 80, seed: int = 42) -> int:
    chunks = [c for c in read_jsonl(INDEX_DIR / "chunks.jsonl") if len(c["text"]) >= min_chunk_chars]
    random.Random(seed).shuffle(chunks)
    if limit:
        chunks = chunks[:limit]

    done: set[str] = set()
    seen_questions: set[str] = set()
    if out_path.exists():
        for item in read_jsonl(out_path):
            done.add(item["chunk_id"])
            seen_questions.add(item["question"])
    todo = [c for c in chunks if c["id"] not in done]
    print(f"[出题] 共 {len(chunks)} 段资料，已完成 {len(chunks) - len(todo)} 段，本次处理 {len(todo)} 段")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    total, t0 = 0, time.time()
    with open(out_path, "a", encoding="utf-8") as f:
        for k, c in enumerate(todo, 1):
            context = f"{chunk_header(c)}\n{c['text']}"
            messages = [{"role": "user", "content": QA_PROMPT.format(n=per_chunk, context=context)}]
            output = "".join(backend.stream(messages, max_new_tokens=160 * per_chunk))
            pairs = filter_qa(parse_qa(output), c["text"], min_grounding)
            written = 0
            for q, a in pairs[:per_chunk]:
                if q in seen_questions:
                    continue
                seen_questions.add(q)
                f.write(json.dumps({"question": q, "answer": a, "chunk_id": c["id"], "doc": c["doc"]},
                                   ensure_ascii=False) + "\n")
                written += 1
            if not written:  # 记录空结果，续跑时不再重复处理这一段
                f.write(json.dumps({"question": "", "answer": "", "chunk_id": c["id"], "doc": c["doc"]},
                                   ensure_ascii=False) + "\n")
            f.flush()
            total += written
            eta = (time.time() - t0) / k * (len(todo) - k)
            print(f"\r  {k}/{len(todo)} 段，新增问答 {total} 条，预计还需 {eta / 60:.0f} 分钟", end="", flush=True)
    print(f"\n[出题] 完成，结果保存在 {out_path}")
    return total

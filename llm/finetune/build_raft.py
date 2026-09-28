"""第 2 步：把问答对做成 RAFT 训练样本（Retrieval-Augmented Fine-Tuning）。

每条样本 = 问题 + 1 段正确资料 + 若干段干扰资料（位置随机），答案带引用编号；
另有一部分样本故意去掉正确资料，答案是"知识库中未找到相关信息。"。
这样训练出来的小模型：不被无关资料带偏、会标引用、没有答案时会拒答。
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from common import read_jsonl, write_jsonl
from config import INDEX_DIR, MAX_CONTEXT_CHARS, OUTPUT_DIR
from finetune.gen_qa import grounding
from kb_builder.bm25 import BM25
from serve.prompt import REFUSAL, build_messages


def add_citation(answer: str, n: int) -> str:
    answer = answer.strip()
    if re.search(r"\[\d+\]", answer):
        return answer
    m = re.search(r"[。！？.!?]+$", answer)
    if m:
        return f"{answer[:m.start()]}[{n}]{m.group()}"
    return f"{answer}[{n}]"


def build_raft(qa_path: Path = OUTPUT_DIR / "qa.jsonl", out_path: Path = OUTPUT_DIR / "train.jsonl",
               neg_ratio: float = 0.2, n_distractors: int = 2, variants: int = 1, seed: int = 42) -> int:
    rng = random.Random(seed)
    chunks = read_jsonl(INDEX_DIR / "chunks.jsonl")
    by_id = {c["id"]: c for c in chunks}
    bm25 = BM25.load(INDEX_DIR / "bm25.json.gz")
    qas = [x for x in read_jsonl(qa_path) if x.get("question") and x.get("chunk_id") in by_id]
    if not qas:
        raise SystemExit(f"{qa_path} 中没有可用的问答，请先运行 gen-qa（或检查知识库是否重建过）")

    samples = []
    for qa in qas:
        golden = by_id[qa["chunk_id"]]
        # 干扰资料只从其他文档里挑，并且不能恰好包含答案，否则"拒答"标签会出错
        pool = [chunks[i] for i, _ in bm25.search(qa["question"], 30) if chunks[i]["doc"] != golden["doc"]]
        others = [c for c in chunks if c["doc"] != golden["doc"]]
        if not others:
            continue
        for _ in range(variants):
            negative = rng.random() < neg_ratio
            need = n_distractors + (1 if negative else 0)
            hard = rng.sample(pool[:6], min(len(pool[:6]), need - 1)) if pool else []
            candidates = hard + rng.sample(others, min(len(others), need * 3))
            distractors: list[dict] = []
            for c in candidates:
                if len(distractors) >= need:
                    break
                if c["id"] not in {d["id"] for d in distractors} and grounding(qa["answer"], c["text"]) < 0.5:
                    distractors.append(c)
            contexts = distractors if negative else distractors + [golden]
            rng.shuffle(contexts)
            while sum(len(c["text"]) for c in contexts) > MAX_CONTEXT_CHARS and len(contexts) > 1:
                contexts.remove(next(c for c in contexts if c is not golden))  # 超长时去掉干扰资料
            if negative:
                answer = REFUSAL
            else:
                answer = add_citation(qa["answer"], contexts.index(golden) + 1)
            messages = build_messages(qa["question"], contexts)
            messages.append({"role": "assistant", "content": answer})
            samples.append({"messages": messages, "negative": negative})

    rng.shuffle(samples)
    write_jsonl(out_path, samples)
    n_neg = sum(s["negative"] for s in samples)
    print(f"[训练集] {len(samples)} 条（其中拒答样本 {n_neg} 条），保存在 {out_path}")
    return len(samples)

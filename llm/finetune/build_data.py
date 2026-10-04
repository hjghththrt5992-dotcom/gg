"""第 3 步：把原文、改写和问答混合成训练集。

训练集里有两种样本：
- {"text": ...}      原文和改写，模型学习整段文字（相当于"读书"，把知识写进参数）
- {"messages": ...}  问答对话，只对回答部分计算损失（学会"被问到时把知识说出来"）
另外留出一部分问答不参与训练，作为自动评测题，检验模型是否真的学会了知识，而不是只背住了训练题。
"""
from __future__ import annotations

import random
from collections import defaultdict

from common import read_jsonl, write_jsonl
from config import EVAL_AUTO, PASSAGES, QA, REWRITES, TRAIN_FILE
from kb_builder.chunker import chunk_header, passage_text
from serve.prompt import build_messages

RECALL_TEMPLATES = ["请介绍一下《{title}》中的“{section}”。", "《{title}》里关于“{section}”讲了什么？"]


def _chat(question: str, answer: str) -> dict:
    return {"messages": build_messages(question) + [{"role": "assistant", "content": answer}]}


def estimate_tokens(samples: list[dict]) -> int:
    """粗略估算词元数：中文约 0.7 词元/字，对话模板约 40 词元。"""
    total = 0
    for s in samples:
        if "text" in s:
            total += int(len(s["text"]) * 0.7) + 2
        else:
            total += int(sum(len(m["content"]) for m in s["messages"]) * 0.7) + 40
    return total


def build_dataset(eval_ratio: float = 0.1, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    passages = read_jsonl(PASSAGES)
    by_id = {p["id"]: p for p in passages}
    rewrites = [r for r in read_jsonl(REWRITES) if r.get("text")] if REWRITES.exists() else []
    qas = [q for q in read_jsonl(QA) if q.get("question")] if QA.exists() else []

    # 1) 原文 + 改写：整段学习
    texts = [{"text": passage_text(p)} for p in passages]
    texts += [{"text": f"{chunk_header(by_id[r['passage']])}\n{r['text']}"} for r in rewrites if r["passage"] in by_id]

    # 2) 主题回忆：问某个小节讲了什么 → 回答该小节原文（只用没有被切成多段的小节，避免同一问题有不同答案）
    sections: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in passages:
        if p.get("section"):
            sections[(p["doc"], p["section"])].append(p)
    recalls = []
    for (_, section), group in sections.items():
        if len(group) == 1:
            p = group[0]
            name = section.split(" > ")[-1]
            for t in RECALL_TEMPLATES:
                recalls.append(_chat(t.format(title=p["title"], section=name), p["text"]))

    # 3) 问答：留出一部分做评测
    unique = list({q["question"]: q for q in qas}.values())
    rng.shuffle(unique)
    n_eval = int(len(unique) * eval_ratio) if len(unique) >= 20 else 0
    held_out, train_qa = unique[:n_eval], unique[n_eval:]
    if held_out:
        write_jsonl(EVAL_AUTO, [{"question": q["question"], "answer": q["answer"], "doc": q["doc"]} for q in held_out])
    else:
        EVAL_AUTO.unlink(missing_ok=True)  # 问答太少（不到 20 道）时不留评测题
    chats = [_chat(q["question"], q["answer"]) for q in train_qa]

    samples = texts + recalls + chats
    rng.shuffle(samples)
    write_jsonl(TRAIN_FILE, samples)
    print(f"[训练集] 原文 {len(passages)} 段 + 改写 {len(texts) - len(passages)} 段 + 主题回忆 {len(recalls)} 条 "
          f"+ 问答 {len(chats)} 条 = {len(samples)} 条，约 {estimate_tokens(samples) / 10000:.1f} 万词元/轮")
    if held_out:
        print(f"[训练集] 留出 {len(held_out)} 道问答做评测：{EVAL_AUTO}")
    if not rewrites:
        print("[提示] 没有改写数据。先运行 rewrite，模型会记得更牢。")
    if not qas:
        print("[提示] 没有问答数据。先运行 gen-qa，模型才学得会回答问题。")
    print(f"保存在 {TRAIN_FILE}")
    return samples

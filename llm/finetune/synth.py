"""第 2 步：用底座模型把知识库段落"加工"成训练数据。

知识要写进模型参数里，只把原文读几遍是不够的：研究发现（Allen-Zhu & Li,《Physics of Language Models》），
同一条知识必须以多种不同的说法出现，模型才能在被提问时把它说出来。所以这里做两件事：
- rewrite：把每段资料用几种不同的风格改写（保留全部事实、数字、名称）
- qa：根据每段资料出问答题，训练模型"被问到时能答出来"

生成结果都会自动过滤（答案/改写必须能在原文中找到依据，不能凭空多出数字），并支持断点续跑。
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Callable

from common import read_jsonl
from config import PASSAGES, QA, REWRITES
from kb_builder.chunker import passage_text

QA_PROMPT = (
    "请根据下面的资料，出 {n} 道能直接从资料中找到答案的问答题。\n"
    "要求：\n"
    "1. 问题要具体、完整，写明在问什么东西（例如“LoRA 的秩一般取多少？”，而不是“它的秩取多少？”），"
    "不要出现“资料”“文中”“上文”“本文”等字眼；\n"
    "2. 答案用一到三句话，内容完全来自资料；\n"
    "3. 严格按以下格式输出，不要输出其他内容：\n"
    "问：……\n答：……\n\n"
    "资料：\n{context}"
)
REWRITE_STYLES = [
    "用通俗易懂的语言重新讲解一遍，像老师给学生讲课一样",
    "整理成条理清晰的要点笔记，每个要点占一行",
    "换一种句式和叙述顺序复述，尽量使用不同的词语",
    "改写成一段简洁的百科式介绍",
]
REWRITE_PROMPT = (
    "请把下面的资料{style}。\n"
    "要求：保留资料中全部的事实、数字、名称和术语，不要遗漏要点，不要添加资料中没有的内容。"
    "只输出改写后的内容，不要加任何说明。\n\n"
    "资料：\n{context}"
)
BAD_QUESTION = re.compile(r"资料|文中|上文|本文|这段|该段|原文|以上|下列")
LEADING_REF = re.compile(r"^(根据|按照|依据)(以上|上述|这段)?(资料|材料|上文|原文|文中)(所述|内容)?[，,：:]?\s*")
QA_PATTERN = re.compile(r"问[:：]\s*(.+?)\s*\n+\s*答[:：]\s*(.+?)(?=\n\s*问[:：]|\Z)", re.S)
REWRITE_PREFIX = re.compile(r"^\s*(改写后的?(内容|资料)?|以下是改写后的内容)[:：]\s*")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def bigrams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def grounding(text: str, source: str) -> float:
    """text 中有多大比例的二元组出现在 source 里。"""
    a = bigrams(text)
    return len(a & bigrams(source)) / max(1, len(a))


def key_numbers(text: str) -> set[str]:
    """两位以上的数字和小数（一位整数多半是序号，不算）。"""
    return {n for n in NUMBER.findall(text) if len(n) > 1}


# ---------------- 问答 ----------------

def parse_qa(output: str) -> list[tuple[str, str]]:
    # 小模型常写"根据资料，……？"，去掉这种开头，保留问题本身
    return [(LEADING_REF.sub("", q.strip()), a.strip()) for q, a in QA_PATTERN.findall(output)]


def filter_qa(pairs: list[tuple[str, str]], source: str, min_grounding: float = 0.6) -> list[tuple[str, str]]:
    kept = []
    for q, a in pairs:
        if not (5 <= len(q) <= 80 and 2 <= len(a) <= 300):
            continue
        if BAD_QUESTION.search(q) or grounding(a, source) < min_grounding:
            continue
        if not key_numbers(a) <= key_numbers(source):  # 答案里出现了原文没有的数字
            continue
        kept.append((q, a))
    return kept


# ---------------- 改写 ----------------

def clean_rewrite(output: str) -> str:
    return REWRITE_PREFIX.sub("", output.strip()).strip()


def accept_rewrite(rewrite: str, source: str) -> bool:
    if not 0.4 <= len(rewrite) / max(1, len(source)) <= 2.5:
        return False
    if grounding(rewrite, source) < 0.35:  # 跑题了
        return False
    nums, new_nums = key_numbers(source), key_numbers(rewrite)
    if not new_nums <= nums:  # 编造了数字
        return False
    return len(nums & new_nums) >= 0.7 * len(nums)  # 关键数字基本都保留了


# ---------------- 通用生成循环 ----------------

def _generate(backend, jobs: list[tuple[str, dict, list[dict], int]], out_path: Path,
              handle: Callable[[dict, str], list[dict]], label: str) -> int:
    """jobs: (任务键, 段落, 提示消息, 最大生成长度)。每个任务的结果追加写入 out_path，已完成的任务会跳过。"""
    done = {item["job"] for item in read_jsonl(out_path)} if out_path.exists() else set()
    todo = [j for j in jobs if j[0] not in done]
    print(f"[{label}] 共 {len(jobs)} 个任务，已完成 {len(jobs) - len(todo)} 个，本次处理 {len(todo)} 个")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total, t0 = 0, time.time()
    with open(out_path, "a", encoding="utf-8") as f:
        for k, (job, passage, messages, max_new) in enumerate(todo, 1):
            output = "".join(backend.stream(messages, max_new_tokens=max_new))
            records = handle(passage, output)
            for r in records:
                f.write(json.dumps(dict(r, job=job), ensure_ascii=False) + "\n")
            if not records:  # 记录空结果，续跑时不再重复处理
                f.write(json.dumps({"job": job, "empty": True}, ensure_ascii=False) + "\n")
            f.flush()
            total += len(records)
            eta = (time.time() - t0) / k * (len(todo) - k)
            print(f"\r  {k}/{len(todo)}，新增 {total} 条，预计还需 {eta / 60:.0f} 分钟", end="", flush=True)
    print(f"\n[{label}] 完成，保存在 {out_path}")
    return total


def _passages(limit: int | None, seed: int, min_chars: int = 80) -> list[dict]:
    passages = [p for p in read_jsonl(PASSAGES) if len(p["text"]) >= min_chars]
    random.Random(seed).shuffle(passages)
    return passages[:limit] if limit else passages


def generate_qa(backend, per_passage: int = 3, limit: int | None = None, seed: int = 42) -> int:
    seen: set[str] = set()

    def handle(p: dict, output: str) -> list[dict]:
        records = []
        for q, a in filter_qa(parse_qa(output), p["text"])[:per_passage]:
            if q not in seen:
                seen.add(q)
                records.append({"question": q, "answer": a, "passage": p["id"], "doc": p["doc"]})
        return records

    jobs = [(p["id"], p, [{"role": "user", "content": QA_PROMPT.format(n=per_passage, context=passage_text(p))}],
             160 * per_passage) for p in _passages(limit, seed)]
    return _generate(backend, jobs, QA, handle, "出题")


def generate_rewrites(backend, per_passage: int = 2, limit: int | None = None, seed: int = 42) -> int:
    def handle(p: dict, output: str) -> list[dict]:
        text = clean_rewrite(output)
        return [{"passage": p["id"], "text": text}] if accept_rewrite(text, p["text"]) else []

    jobs = []
    for p in _passages(limit, seed):
        for i, style in enumerate(REWRITE_STYLES[:per_passage]):
            prompt = REWRITE_PROMPT.format(style=style, context=passage_text(p))
            jobs.append((f"{p['id']}@{i}", p, [{"role": "user", "content": prompt}], len(p["text"]) * 2 + 64))
    return _generate(backend, jobs, REWRITES, handle, "改写")

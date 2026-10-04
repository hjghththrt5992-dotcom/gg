"""评测：不给任何资料，直接提问，看模型有没有学会知识库里的内容（闭卷考试）。

评测题每行一个 JSON，两种判分方式：
  {"question": "...", "keywords": ["必须出现的词", "同义词A|同义词B"]}   关键词全部出现算对
  {"question": "...", "answer": "参考答案"}                             参考答案的二元组有一半以上出现在回答里算对
自带评测题 kb/eval.jsonl 针对示例知识库；build-train 还会从生成的问答里留出一部分作为自动评测题。
建议训练前后各测一次：eval --base 测原版底座模型，eval 测训练后的模型。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from common import read_jsonl
from config import OUTPUT_DIR
from finetune.synth import grounding
from serve.prompt import build_messages


def keywords_hit(answer: str, keywords: list[str]) -> bool:
    text = answer.lower()
    return all(any(alt.strip().lower() in text for alt in group.split("|")) for group in keywords)


def judge(item: dict, answer: str) -> bool:
    if item.get("keywords"):
        return keywords_hit(answer, item["keywords"])
    return grounding(item.get("answer", ""), answer) >= 0.5


def evaluate(backend, eval_path: Path, tag: str, limit: int | None = None) -> dict:
    items = read_jsonl(eval_path)[:limit] if limit else read_jsonl(eval_path)
    if not items:
        raise SystemExit(f"{eval_path} 中没有评测题")
    correct, details, t0 = 0, [], time.time()
    for k, item in enumerate(items, 1):
        answer = "".join(backend.stream(build_messages(item["question"]))).strip()
        ok = judge(item, answer)
        correct += ok
        details.append({"question": item["question"], "answer": answer, "correct": ok,
                        "reference": item.get("answer") or item.get("keywords")})
        print(f"\r  [{eval_path.name}] {k}/{len(items)}，答对 {correct}", end="", flush=True)
    elapsed = time.time() - t0
    report = {"tag": tag, "file": str(eval_path), "model": backend.label, "accuracy": correct / len(items),
              "correct": correct, "total": len(items), "seconds_per_question": elapsed / len(items),
              "details": details}
    print(f"\n  正确率 {100 * correct / len(items):.1f}%（{correct}/{len(items)}），"
          f"平均每题 {elapsed / len(items):.1f} 秒")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"eval_{tag}_{eval_path.stem}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  每道题的回答：{out}")
    return report

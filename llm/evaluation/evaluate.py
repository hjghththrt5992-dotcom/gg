"""评测：用数字衡量"效果好不好"。

评测集每行一个 JSON：
  可回答：{"question": "...", "doc": "应命中的文档文件名", "keywords": ["必须出现的词", "同义词A|同义词B"]}
  不可回答（知识库里没有）：{"question": "...", "doc": null}
指标：
  检索命中率 Hit@1 / Hit@K、MRR —— 正确文档是否被检索到
  回答正确率 —— 关键词全部出现；没有 keywords 时，参考答案 answer 与回答的二元组重合率 ≥ 0.5
  引用正确率 —— 答案引用的编号中，是否有来自正确文档的资料
  拒答正确率 —— 知识库外的问题，是否回答"未找到"；以及可回答问题被错误拒答的比例
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from common import read_jsonl
from config import CANDIDATES, KB_EVAL, OUTPUT_DIR, TOP_K
from finetune.gen_qa import grounding
from serve.chat import cited_numbers
from serve.prompt import is_refusal


def keywords_hit(answer: str, keywords: list[str]) -> bool:
    text = answer.lower()
    return all(any(alt.strip().lower() in text for alt in group.split("|")) for group in keywords)


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:.1f}%（{num}/{den}）" if den else "-"


def evaluate(retriever, rag=None, eval_path: Path = KB_EVAL, tag: str = "base", limit: int | None = None) -> dict:
    items = read_jsonl(eval_path)[:limit] if limit else read_jsonl(eval_path)
    answerable = [x for x in items if x.get("doc")]
    unanswerable = [x for x in items if not x.get("doc")]

    # ---- 检索 ----
    hit1 = hitk = 0
    mrr = 0.0
    for x in answerable:
        hits = retriever.search(x["question"], top_k=CANDIDATES)
        ranks = [i for i, h in enumerate(hits) if h["doc"] == x["doc"]]
        rank = ranks[0] if ranks else None
        x["_rank"] = rank
        hit1 += rank == 0
        hitk += rank is not None and rank < TOP_K
        mrr += 1 / (rank + 1) if rank is not None else 0
    report = {
        "tag": tag,
        "retrieval": {"hit@1": hit1 / max(1, len(answerable)), f"hit@{TOP_K}": hitk / max(1, len(answerable)),
                      "mrr": mrr / max(1, len(answerable))},
    }
    print(f"\n==== 检索（{len(answerable)} 题）====")
    print(f"  Hit@1     {_pct(hit1, len(answerable))}")
    print(f"  Hit@{TOP_K}     {_pct(hitk, len(answerable))}")
    print(f"  MRR       {report['retrieval']['mrr']:.3f}")

    if rag is None:
        return report

    # ---- 生成 ----
    correct = cite_ok = false_refuse = refuse_ok = 0
    details = []
    t0 = time.time()
    for k, x in enumerate(items, 1):
        contexts, answer = rag.answer(x["question"])
        refused = is_refusal(answer)
        row = {"question": x["question"], "answer": answer, "doc": x.get("doc"), "refused": refused}
        if x.get("doc"):
            if x.get("keywords"):
                ok = keywords_hit(answer, x["keywords"])
            else:
                ok = grounding(x.get("answer", ""), answer) >= 0.5
            cited_docs = {contexts[n - 1]["doc"] for n in cited_numbers(answer) if 0 < n <= len(contexts)}
            row.update(correct=ok and not refused, cited_ok=x["doc"] in cited_docs)
            correct += row["correct"]
            cite_ok += row["cited_ok"]
            false_refuse += refused
        else:
            row["correct"] = refused
            refuse_ok += refused
        details.append(row)
        print(f"\r  生成中 {k}/{len(items)}", end="", flush=True)
    elapsed = time.time() - t0

    report["generation"] = {
        "accuracy": correct / max(1, len(answerable)),
        "citation": cite_ok / max(1, len(answerable)),
        "false_refusal": false_refuse / max(1, len(answerable)),
        "refusal": refuse_ok / max(1, len(unanswerable)),
        "seconds_per_question": elapsed / max(1, len(items)),
    }
    report["details"] = details
    print(f"\n==== 回答（模型：{rag.backend.label}）====")
    print(f"  回答正确率     {_pct(correct, len(answerable))}")
    print(f"  引用正确率     {_pct(cite_ok, len(answerable))}")
    print(f"  错误拒答率     {_pct(false_refuse, len(answerable))}  （越低越好）")
    print(f"  拒答正确率     {_pct(refuse_ok, len(unanswerable))}  （知识库外的问题）")
    print(f"  平均每题用时   {report['generation']['seconds_per_question']:.1f} 秒")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"eval_{tag}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  详细结果：{out}")
    return report

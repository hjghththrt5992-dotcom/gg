"""提示词。训练（RAFT 微调）和推理必须使用完全相同的格式。"""
from __future__ import annotations

from config import MAX_CONTEXT_CHARS
from kb_builder.chunker import chunk_header

REFUSAL = "知识库中未找到相关信息。"

SYSTEM_PROMPT = (
    "你是一个知识库问答助手。请严格依据【参考资料】回答【问题】：\n"
    "1. 只使用参考资料中的信息，不要编造，不要使用资料以外的知识；\n"
    "2. 在用到资料的句子末尾标注资料编号，如 [1]、[2]；\n"
    f"3. 如果参考资料中没有能回答问题的内容，只回答：{REFUSAL}\n"
    "4. 回答简洁、准确，使用中文。"
)


def select_context(hits: list[dict], max_chars: int = MAX_CONTEXT_CHARS) -> list[dict]:
    """按相关度顺序取资料，直到达到字数上限（至少保留 1 段）。"""
    picked, total = [], 0
    for h in hits:
        n = len(h["text"])
        if picked and total + n > max_chars:
            break
        picked.append(h)
        total += n
    return picked


def build_messages(question: str, contexts: list[dict]) -> list[dict]:
    parts = [f"[{i}] {chunk_header(c)}\n{c['text']}" for i, c in enumerate(contexts, 1)]
    user = "【参考资料】\n" + "\n\n".join(parts) + f"\n\n【问题】\n{question.strip()}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def is_refusal(answer: str) -> bool:
    return "未找到相关信息" in answer or "没有找到相关信息" in answer

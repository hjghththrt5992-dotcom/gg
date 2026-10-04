"""对话格式。训练和推理必须使用完全相同的系统提示词。"""
from __future__ import annotations

SYSTEM_PROMPT = "你是一个知识问答助手，请准确、简洁地用中文回答用户的问题。"


def build_messages(question: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question.strip()},
    ]

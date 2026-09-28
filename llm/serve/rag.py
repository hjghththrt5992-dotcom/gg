"""检索增强生成：检索资料 → 拼提示词 → 小模型生成带引用的答案。"""
from __future__ import annotations

from typing import Iterator

from config import TOP_K
from serve.prompt import build_messages, select_context


class RAG:
    def __init__(self, retriever, backend, top_k: int = TOP_K):
        self.retriever = retriever
        self.backend = backend
        self.top_k = top_k

    def ask(self, question: str) -> tuple[list[dict], Iterator[str]]:
        """返回 (引用的资料, 答案的流式输出)。"""
        contexts = select_context(self.retriever.search(question, top_k=self.top_k))
        return contexts, self.backend.stream(build_messages(question, contexts))

    def answer(self, question: str) -> tuple[list[dict], str]:
        contexts, stream = self.ask(question)
        return contexts, "".join(stream).strip()

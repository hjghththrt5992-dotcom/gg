"""命令行对话。"""
from __future__ import annotations

import re
import time

from kb_builder.chunker import chunk_header


def cited_numbers(answer: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[(\d+)\]", answer)}


def format_sources(contexts: list[dict], answer: str) -> str:
    cited = cited_numbers(answer)
    lines = []
    for i, c in enumerate(contexts, 1):
        mark = "*" if i in cited else " "
        lines.append(f"  {mark}[{i}] {chunk_header(c)}  ({c['doc']})")
    return "\n".join(lines)


def run_chat(rag) -> None:
    print(f"[模型] {rag.backend.label}（{rag.backend.name}）")
    print("输入问题开始提问，输入 /q 退出。\n")
    while True:
        try:
            question = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question in {"/q", "/quit", "exit", "quit", "退出"}:
            break
        t0 = time.time()
        contexts, stream = rag.ask(question)
        print("助手：", end="", flush=True)
        parts = []
        for piece in stream:
            parts.append(piece)
            print(piece, end="", flush=True)
        answer = "".join(parts)
        print(f"\n\n参考资料（* 为答案引用）  用时 {time.time() - t0:.1f} 秒")
        print(format_sources(contexts, answer) + "\n")

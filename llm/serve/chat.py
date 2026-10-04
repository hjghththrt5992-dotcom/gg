"""命令行对话。"""
from __future__ import annotations

import time

from serve.prompt import build_messages


def run_chat(backend) -> None:
    print(f"[模型] {backend.label}（{backend.name}）")
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
        print("助手：", end="", flush=True)
        for piece in backend.stream(build_messages(question)):
            print(piece, end="", flush=True)
        print(f"\n（用时 {time.time() - t0:.1f} 秒）\n")

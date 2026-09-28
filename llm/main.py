"""统一入口。用法：python llm/main.py <命令> [参数]，python llm/main.py -h 查看全部命令。

快速开始：
  python llm/main.py check        检测电脑配置，推荐模型大小
  python llm/main.py download     下载模型（国内自动走镜像）
  python llm/main.py build        构建知识库索引
  python llm/main.py chat         命令行问答
  python llm/main.py web          网页问答

微调（可选，让小模型更会"按资料答题"）：
  python llm/main.py gen-qa       从知识库自动出题
  python llm/main.py build-train  生成 RAFT 训练样本
  python llm/main.py train        LoRA 微调
  python llm/main.py eval --finetuned   评测微调效果
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")  # 只显示错误，界面更清爽
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
for stream in (sys.stdout, sys.stderr):  # Windows 终端默认 GBK，统一改成 UTF-8 避免乱码
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from config import INDEX_DIR, KB_DOCS, KB_EVAL, LLM_MODELS, OUTPUT_DIR, default_size, load_settings, model_dir  # noqa: E402


def _add_model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--size", choices=list(LLM_MODELS), help="模型大小（默认用 check 推荐的）")
    p.add_argument("--backend", choices=["auto", "gguf", "hf"], default="auto", help="推理后端")
    p.add_argument("--model", help="指定模型路径（目录或 .gguf 文件）")
    p.add_argument("--adapter", help="LoRA 微调结果目录")
    p.add_argument("--finetuned", action="store_true", help=f"使用微调结果（{OUTPUT_DIR / 'lora'}）")
    p.add_argument("--rerank", action="store_true", help="启用重排模型（更准，更慢）")


def _load_rag(args, retriever=None):
    from retriever.hybrid import Retriever
    from serve.backends import load_backend
    from serve.rag import RAG

    retriever = retriever or Retriever(use_rerank=args.rerank)
    backend = load_backend(args.size or default_size(), args.backend, args.model, args.adapter, args.finetuned)
    return RAG(retriever, backend)


def cmd_check(args):
    from prepare.check_env import check

    check()


def cmd_download(args):
    from prepare.download import download

    size = args.size or default_size()
    train_size = load_settings().get("train_size", size)
    download(size, gguf=args.gguf, rerank=args.rerank, source=args.source, extra_sizes=(train_size,))


def cmd_build(args):
    from kb_builder.build import build_index

    print(f"[构建索引] 文档目录 {args.docs}")
    build_index(Path(args.docs), INDEX_DIR, use_embed=not args.no_embed)


def cmd_ask(args):
    from serve.chat import format_sources

    rag = _load_rag(args)
    contexts, stream = rag.ask(args.question)
    answer = ""
    for piece in stream:
        answer += piece
        print(piece, end="", flush=True)
    print("\n\n参考资料（* 为答案引用）\n" + format_sources(contexts, answer))


def cmd_chat(args):
    from serve.chat import run_chat

    run_chat(_load_rag(args))


def cmd_web(args):
    from serve.web import run_web

    run_web(_load_rag(args), args.host, args.port)


def cmd_gen_qa(args):
    from finetune.gen_qa import generate_qa
    from serve.backends import load_backend

    backend = load_backend(args.size or default_size(), args.backend, args.model)
    generate_qa(backend, per_chunk=args.per_chunk, limit=args.limit)


def cmd_build_train(args):
    from finetune.build_raft import build_raft

    build_raft(neg_ratio=args.neg_ratio, n_distractors=args.distractors, variants=args.variants)


def cmd_train(args):
    from finetune.train_lora import train_lora

    size = args.size or load_settings().get("train_size", "0.5b")
    base = Path(args.model) if args.model else model_dir(LLM_MODELS[size])
    if not (base / "config.json").exists():
        raise SystemExit(f"找不到底座模型 {base}，请先运行 download --size {size}")
    train_lora(base, epochs=args.epochs, lr=args.lr, rank=args.rank, grad_accum=args.grad_accum,
               max_samples=args.max_samples, resume=args.resume)


def cmd_merge(args):
    from finetune.merge import merge_lora

    merge_lora(Path(args.adapter) if args.adapter else OUTPUT_DIR / "lora")


def cmd_eval(args):
    from evaluation.evaluate import evaluate
    from retriever.hybrid import Retriever

    retriever = Retriever(use_rerank=args.rerank)
    rag = None if args.retrieval_only else _load_rag(args, retriever)
    tag = args.tag or ("finetuned" if (args.finetuned or args.adapter) else "base")
    evaluate(retriever, rag, Path(args.file), tag=tag, limit=args.limit)


def main():
    try:
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="低成本知识库问答模型", formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="检测电脑配置，推荐模型大小").set_defaults(func=cmd_check)

    p = sub.add_parser("download", help="下载模型")
    p.add_argument("--size", choices=list(LLM_MODELS))
    p.add_argument("--gguf", action="store_true", help="同时下载 GGUF 量化模型（需 llama-cpp-python）")
    p.add_argument("--rerank", action="store_true", help="同时下载重排模型")
    p.add_argument("--source", choices=["auto", "hf", "mirror"], default="auto", help="下载源")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("build", help="构建知识库索引")
    p.add_argument("--docs", default=str(KB_DOCS), help="文档目录")
    p.add_argument("--no-embed", action="store_true", help="不使用向量模型，只建关键词索引")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("ask", help="问一个问题")
    p.add_argument("question")
    _add_model_args(p)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("chat", help="命令行问答")
    _add_model_args(p)
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("web", help="网页问答")
    _add_model_args(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("gen-qa", help="微调第 1 步：从知识库自动出题")
    p.add_argument("--size", choices=list(LLM_MODELS))
    p.add_argument("--backend", choices=["auto", "gguf", "hf"], default="auto")
    p.add_argument("--model", help="出题用的模型（越大题目质量越高）")
    p.add_argument("--per-chunk", type=int, default=2, help="每段资料出几道题")
    p.add_argument("--limit", type=int, help="最多处理多少段资料")
    p.set_defaults(func=cmd_gen_qa)

    p = sub.add_parser("build-train", help="微调第 2 步：生成 RAFT 训练样本")
    p.add_argument("--neg-ratio", type=float, default=0.2, help="拒答样本比例")
    p.add_argument("--distractors", type=int, default=2, help="每条样本的干扰资料数")
    p.add_argument("--variants", type=int, default=1, help="每道题生成几条样本（数据少时可设 2~3）")
    p.set_defaults(func=cmd_build_train)

    p = sub.add_parser("train", help="微调第 3 步：LoRA 训练")
    p.add_argument("--size", choices=list(LLM_MODELS), help="底座大小（默认用 check 推荐的）")
    p.add_argument("--model", help="指定底座模型目录")
    p.add_argument("--epochs", type=float, default=1.0)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--max-samples", type=int, help="最多用多少条样本（先小规模试跑）")
    p.add_argument("--resume", action="store_true", help="从上次中断处继续")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("merge", help="把 LoRA 合并进底座模型（转 GGUF 前用）")
    p.add_argument("--adapter")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("eval", help="评测检索和回答效果")
    _add_model_args(p)
    p.add_argument("--file", default=str(KB_EVAL), help="评测集")
    p.add_argument("--retrieval-only", action="store_true", help="只评测检索（不需要模型，几秒完成）")
    p.add_argument("--limit", type=int)
    p.add_argument("--tag", help="结果文件名标签")
    p.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

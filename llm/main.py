"""统一入口。用法：python llm/main.py <命令> [参数]，python llm/main.py -h 查看全部命令。

准备：
  python llm/main.py check        检测电脑配置，推荐底座模型大小
  python llm/main.py download     下载底座模型（国内自动走镜像）

用知识库训练模型（每一步都可以中断后重新运行，会接着做）：
  python llm/main.py build        1. 把知识库文档切成段落
  python llm/main.py rewrite      2. 用不同说法改写每段（同一知识多种说法，模型才记得牢）
  python llm/main.py gen-qa       3. 根据每段出问答题
  python llm/main.py build-train  4. 混合成训练集
  python llm/main.py train        5. LoRA 训练，把知识写进模型
  python llm/main.py auto         一键依次完成以上 5 步

使用和评测：
  python llm/main.py chat         命令行问答（默认用训练好的模型）
  python llm/main.py web          网页问答
  python llm/main.py eval         评测（加 --base 测原版模型，对比训练效果）
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

from config import (EVAL_AUTO, KB_DOCS, KB_EVAL, LLM_MODELS, LORA_DIR, default_size,  # noqa: E402
                    load_settings, model_dir)


def _add_model_args(p: argparse.ArgumentParser, trained: bool = True) -> None:
    p.add_argument("--size", choices=list(LLM_MODELS), help="底座模型大小（默认用 check 推荐的）")
    p.add_argument("--backend", choices=["auto", "gguf", "hf"], default="auto", help="推理后端")
    p.add_argument("--model", help="指定模型路径（目录或 .gguf 文件）")
    if trained:
        p.add_argument("--adapter", help=f"LoRA 训练结果目录（默认 {LORA_DIR}）")
        p.add_argument("--base", action="store_true", help="使用原版底座模型（不加载训练结果）")


def _backend(args, base: bool = False):
    from serve.backends import load_backend

    return load_backend(args.size or default_size(), args.backend, args.model,
                        getattr(args, "adapter", None), base or getattr(args, "base", False))


def cmd_check(args):
    from prepare.check_env import check

    check()


def cmd_download(args):
    from prepare.download import download

    download([args.size or default_size()], gguf=args.gguf, source=args.source)


def cmd_build(args):
    from kb_builder.build import build_passages

    print(f"[切分] 文档目录 {args.docs}")
    build_passages(Path(args.docs))


def cmd_rewrite(args):
    from finetune.synth import generate_rewrites

    generate_rewrites(_backend(args, base=True), per_passage=args.per_passage, limit=args.limit)


def cmd_gen_qa(args):
    from finetune.synth import generate_qa

    generate_qa(_backend(args, base=True), per_passage=args.per_passage, limit=args.limit)


def cmd_build_train(args):
    from finetune.build_data import build_dataset, estimate_tokens
    from prepare.check_env import estimate_hours

    samples = build_dataset(eval_ratio=args.eval_ratio)
    settings = load_settings()
    if settings.get("gflops"):
        size = getattr(args, "size", None) or default_size()
        hours = estimate_hours(estimate_tokens(samples) * args.epochs, size, settings["gflops"])
        print(f"[预估] 用 {size.upper()} 训练 {args.epochs} 轮约需 {hours:.1f} 小时")


def cmd_train(args):
    from finetune.train_lora import train_lora

    size = args.size or default_size()
    base = Path(args.model) if args.model else model_dir(LLM_MODELS[size])
    if not (base / "config.json").exists():
        raise SystemExit(f"找不到底座模型 {base}，请先运行 download --size {size}")
    train_lora(base, epochs=args.epochs, lr=args.lr, rank=args.rank, grad_accum=args.grad_accum,
               max_samples=args.max_samples, resume=args.resume)


def cmd_auto(args):
    from config import PASSAGES

    defaults = dict(size=args.size, backend=args.backend, model=None, limit=None)
    if not PASSAGES.exists() or args.rebuild:
        cmd_build(argparse.Namespace(docs=args.docs))
    if args.rewrites:
        cmd_rewrite(argparse.Namespace(**defaults, per_passage=args.rewrites))
    cmd_gen_qa(argparse.Namespace(**defaults, per_passage=args.qa))
    cmd_build_train(argparse.Namespace(eval_ratio=0.1, epochs=args.epochs, size=args.size))
    cmd_train(argparse.Namespace(size=args.size, model=None, epochs=args.epochs, lr=args.lr, rank=args.rank,
                                 grad_accum=8, max_samples=None, resume=args.resume))


def cmd_ask(args):
    from serve.prompt import build_messages

    for piece in _backend(args).stream(build_messages(args.question)):
        print(piece, end="", flush=True)
    print()


def cmd_chat(args):
    from serve.chat import run_chat

    run_chat(_backend(args))


def cmd_web(args):
    from serve.web import run_web

    run_web(_backend(args), args.host, args.port)


def cmd_eval(args):
    from evaluation.evaluate import evaluate

    files = [Path(args.file)] if args.file else [f for f in (KB_EVAL, EVAL_AUTO) if f.exists()]
    if not files:
        raise SystemExit("没有评测题：请用 --file 指定，或先运行 build-train 生成自动评测题")
    backend = _backend(args)
    tag = args.tag or ("base" if args.base else "trained")
    print(f"[评测] 模型：{backend.label}")
    for f in files:
        evaluate(backend, f, tag=tag, limit=args.limit)


def cmd_merge(args):
    from finetune.merge import merge_lora

    merge_lora(Path(args.adapter) if args.adapter else LORA_DIR)


def main():
    try:
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="低成本知识库训练模型", formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="检测电脑配置，推荐底座模型大小").set_defaults(func=cmd_check)

    p = sub.add_parser("download", help="下载底座模型")
    p.add_argument("--size", choices=list(LLM_MODELS))
    p.add_argument("--gguf", action="store_true", help="同时下载 GGUF 量化版（需 llama-cpp-python，生成训练数据更快）")
    p.add_argument("--source", choices=["auto", "hf", "mirror"], default="auto", help="下载源")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("build", help="1. 把知识库文档切成段落")
    p.add_argument("--docs", default=str(KB_DOCS), help="文档目录")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("rewrite", help="2. 用不同说法改写每段资料")
    _add_model_args(p, trained=False)
    p.add_argument("--per-passage", type=int, default=2, choices=range(1, 5), help="每段改写几种说法（1~4）")
    p.add_argument("--limit", type=int, help="最多处理多少段（先试跑）")
    p.set_defaults(func=cmd_rewrite)

    p = sub.add_parser("gen-qa", help="3. 根据每段资料出问答题")
    _add_model_args(p, trained=False)
    p.add_argument("--per-passage", type=int, default=3, help="每段出几道题")
    p.add_argument("--limit", type=int, help="最多处理多少段（先试跑）")
    p.set_defaults(func=cmd_gen_qa)

    p = sub.add_parser("build-train", help="4. 混合成训练集")
    p.add_argument("--eval-ratio", type=float, default=0.1, help="留出多少比例的问答做评测")
    p.add_argument("--epochs", type=float, default=3, help="（只用于估算训练时间）")
    p.add_argument("--size", choices=list(LLM_MODELS), help="（只用于估算训练时间）")
    p.set_defaults(func=cmd_build_train)

    p = sub.add_parser("train", help="5. LoRA 训练")
    p.add_argument("--size", choices=list(LLM_MODELS), help="底座大小（默认用 check 推荐的）")
    p.add_argument("--model", help="指定底座模型目录")
    p.add_argument("--epochs", type=float, default=3, help="训练轮数，知识记不牢可以加到 4~5")
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=64, help="LoRA 秩，知识越多可以设得越大")
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--max-samples", type=int, help="最多用多少条样本（先小规模试跑）")
    p.add_argument("--resume", action="store_true", help="从上次中断处继续")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("auto", help="一键完成 1~5 步")
    p.add_argument("--size", choices=list(LLM_MODELS))
    p.add_argument("--backend", choices=["auto", "gguf", "hf"], default="auto", help="生成训练数据用的推理后端")
    p.add_argument("--docs", default=str(KB_DOCS))
    p.add_argument("--rebuild", action="store_true", help="重新切分文档（知识库有改动时用）")
    p.add_argument("--rewrites", type=int, default=2, choices=range(0, 5), help="每段改写几种说法，0 表示不改写")
    p.add_argument("--qa", type=int, default=3, help="每段出几道题")
    p.add_argument("--epochs", type=float, default=3)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=64)
    p.add_argument("--resume", action="store_true", help="训练从上次中断处继续")
    p.set_defaults(func=cmd_auto)

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

    p = sub.add_parser("eval", help="闭卷评测：不给资料，看模型学会了多少")
    _add_model_args(p)
    p.add_argument("--file", help=f"评测题文件（默认 {KB_EVAL.name} 和自动留出的评测题）")
    p.add_argument("--limit", type=int, help="每个文件最多测多少题")
    p.add_argument("--tag", help="结果文件名标签")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("merge", help="把 LoRA 合并进底座，得到完整的新模型（转 GGUF 前用）")
    p.add_argument("--adapter")
    p.set_defaults(func=cmd_merge)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

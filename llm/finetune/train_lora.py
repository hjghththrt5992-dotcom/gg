"""第 3 步：LoRA 微调。只训练约 0.5% 的参数，CPU 也能跑；有 NVIDIA 显卡会自动使用。

为了在老电脑上省内存、省时间：
- batch=1 + 梯度累积，不需要 padding；
- 只对答案部分计算 lm_head（logits_to_keep），省掉约 90% 的词表计算和几百 MB 内存；
- 梯度检查点（gradient checkpointing）；
- 定期保存断点，中途关机可以用 --resume 接着训练。
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from common import dtype_kwargs, pick_device, portable_path, read_jsonl, render_chat
from config import OUTPUT_DIR

LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def encode_sample(tokenizer, messages: list[dict], max_len: int):
    """返回 (input_ids, 答案起始位置)。只有答案部分参与计算损失。"""
    prompt = render_chat(tokenizer, messages[:-1], add_generation_prompt=True)
    full = render_chat(tokenizer, messages, add_generation_prompt=False)
    if not full.startswith(prompt):
        raise ValueError("该模型的对话模板不支持按前缀切分答案，请换用 Qwen2.5 系列模型")
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(full[len(prompt):].rstrip("\n"), add_special_tokens=False)["input_ids"]
    ids = prompt_ids + answer_ids
    if len(ids) > max_len:
        return None
    return ids, len(prompt_ids)


def train_lora(base_model: Path, data_path: Path = OUTPUT_DIR / "train.jsonl", out_dir: Path = OUTPUT_DIR / "lora",
               epochs: float = 1.0, lr: float = 2e-4, rank: int = 16, grad_accum: int = 8, max_len: int = 2048,
               max_samples: int | None = None, save_every: int = 20, resume: bool = False, seed: int = 42) -> Path:
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.manual_seed(seed)
    device, dtype = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(str(base_model))

    samples = read_jsonl(data_path)
    random.Random(seed).shuffle(samples)
    if max_samples:
        samples = samples[:max_samples]
    encoded = [e for e in (encode_sample(tokenizer, s["messages"], max_len) for s in samples) if e]
    if not encoded:
        raise SystemExit("没有可用的训练样本")
    n_tokens = sum(len(ids) for ids, _ in encoded)
    n_micro = max(1, int(len(encoded) * epochs))
    order: list[int] = []
    while len(order) < n_micro:  # 每一轮打乱一次顺序
        order += random.Random(seed + len(order)).sample(range(len(encoded)), len(encoded))
    order = order[:n_micro]
    total_steps = math.ceil(n_micro / grad_accum)
    print(f"[训练] 设备 {device}，样本 {len(encoded)} 条（跳过超长 {len(samples) - len(encoded)} 条），"
          f"平均 {n_tokens // len(encoded)} token/条，共 {total_steps} 步")

    model = AutoModelForCausalLM.from_pretrained(str(base_model), **dtype_kwargs(dtype))
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    ckpt_dir = out_dir / "checkpoint"
    if resume and (ckpt_dir / "adapter_config.json").exists():
        model = PeftModel.from_pretrained(model, str(ckpt_dir), is_trainable=True)
    else:
        if resume:
            print("[训练] 没有找到断点，从头开始训练")
            resume = False
        config = LoraConfig(r=rank, lora_alpha=rank * 2, lora_dropout=0.05, target_modules=LORA_TARGETS,
                            task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
    model.to(device)
    model.train()
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"[训练] 可训练参数 {trainable / 1e6:.1f}M / 总参数 {total / 1e6:.0f}M（{100 * trainable / total:.2f}%）")

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    warmup = max(1, total_steps // 20)

    def lr_lambda(step: int) -> float:  # 预热 + 余弦衰减
        if step < warmup:
            return (step + 1) / warmup
        progress = min(1.0, (step - warmup) / max(1, total_steps - warmup))
        return 0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
    step = 0
    if resume:
        state = torch.load(ckpt_dir / "trainer_state.pt", weights_only=False)
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        step = state["step"]
        print(f"[训练] 从第 {step} 步继续")

    def save(path: Path, with_state: bool):
        model.save_pretrained(str(path))
        info = {"base_model": portable_path(base_model), "step": step, "total_steps": total_steps,
                "samples": len(encoded), "rank": rank, "lr": lr}
        (path / "train_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        if with_state:
            torch.save({"optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(), "step": step},
                       path / "trainer_state.pt")

    t0, seen_tokens, running = time.time(), 0, None
    for micro in range(step * grad_accum, len(order)):
        ids, answer_start = encoded[order[micro]]
        input_ids = torch.tensor([ids], device=device)
        keep = len(ids) - answer_start + 1  # 预测答案需要的最后 keep 个位置的 logits
        logits = model(input_ids=input_ids, logits_to_keep=keep).logits[:, :-1].float()
        targets = input_ids[:, answer_start:]
        loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), targets.reshape(-1))
        (loss / grad_accum).backward()
        seen_tokens += len(ids)
        running = loss.item() if running is None else 0.9 * running + 0.1 * loss.item()

        if (micro + 1) % grad_accum == 0 or micro + 1 == len(order):
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            speed = seen_tokens / (time.time() - t0)
            remaining = (len(order) - micro - 1) * (n_tokens / len(encoded)) / max(speed, 1e-9)
            print(f"  步 {step}/{total_steps}  loss {running:.3f}  lr {scheduler.get_last_lr()[0]:.2e}  "
                  f"{speed:.0f} token/秒  预计还需 {remaining / 60:.0f} 分钟", flush=True)
            if step % save_every == 0:
                save(ckpt_dir, with_state=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    save(out_dir, with_state=False)
    print(f"[训练] 完成，用时 {(time.time() - t0) / 60:.1f} 分钟，LoRA 保存在 {out_dir}")
    return out_dir

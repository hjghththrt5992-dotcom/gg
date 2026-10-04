"""全局配置：路径、模型名称、训练参数。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KB_DOCS = ROOT / "kb" / "docs"          # 知识库原始文档：模型要学会的知识（自带示例，可替换成你自己的）
KB_EVAL = ROOT / "kb" / "eval.jsonl"    # 自带评测题
DATA = ROOT / "data"                    # 所有生成的文件（训练数据、模型、训练输出），不进 git
CORPUS_DIR = DATA / "corpus"            # 由知识库生成的训练数据
PASSAGES = CORPUS_DIR / "passages.jsonl"
REWRITES = CORPUS_DIR / "rewrites.jsonl"
QA = CORPUS_DIR / "qa.jsonl"
TRAIN_FILE = CORPUS_DIR / "train.jsonl"
EVAL_AUTO = CORPUS_DIR / "eval_auto.jsonl"
MODELS_DIR = DATA / "models"
OUTPUT_DIR = DATA / "output"
LORA_DIR = OUTPUT_DIR / "lora"
SETTINGS_FILE = DATA / "settings.json"

# ---- 底座模型 ----
LLM_MODELS = {
    "0.5b": "Qwen/Qwen2.5-0.5B-Instruct",
    "1.5b": "Qwen/Qwen2.5-1.5B-Instruct",
}
GGUF_MODELS = {  # llama.cpp 用的 4bit 量化版本（可选）：生成训练数据时速度快 2~4 倍
    "0.5b": ("Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf"),
    "1.5b": ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
}

# ---- 切分 ----
CHUNK_SIZE = 400        # 每段最多字符数
CHUNK_OVERLAP = 60      # 相邻段重叠字符数

# ---- 训练 ----
LORA_RANK = 64          # 注入知识需要较大的秩；只调整回答风格时 8~16 就够
EPOCHS = 3              # 知识要多看几遍才记得住
LEARNING_RATE = 2e-4

# ---- 生成 ----
MAX_NEW_TOKENS = 512
REPETITION_PENALTY = 1.1


def model_dir(repo_id: str) -> Path:
    """模型在本地的存放目录。"""
    return MODELS_DIR / repo_id.replace("/", "__")


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**kwargs) -> None:
    settings = load_settings()
    settings.update(kwargs)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def default_size() -> str:
    """默认使用的模型大小：优先用 check 命令保存的推荐值。"""
    return load_settings().get("size", "0.5b")

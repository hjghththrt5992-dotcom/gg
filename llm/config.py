"""全局配置：路径、模型名称、检索与生成参数。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KB_DOCS = ROOT / "kb" / "docs"          # 知识库原始文档（自带示例，可替换成你自己的）
KB_EVAL = ROOT / "kb" / "eval.jsonl"    # 自带评测集
DATA = ROOT / "data"                    # 所有生成的文件（索引、模型、训练输出），不进 git
INDEX_DIR = DATA / "index"
MODELS_DIR = DATA / "models"
OUTPUT_DIR = DATA / "output"
SETTINGS_FILE = DATA / "settings.json"

# ---- 模型 ----
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"      # 向量模型，约 95MB
RERANK_MODEL = "BAAI/bge-reranker-base"     # 重排模型（可选），约 1.1GB
LLM_MODELS = {
    "0.5b": "Qwen/Qwen2.5-0.5B-Instruct",
    "1.5b": "Qwen/Qwen2.5-1.5B-Instruct",
}
GGUF_MODELS = {  # llama.cpp 用的 4bit 量化版本（可选，推理更快更省内存）
    "0.5b": ("Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf"),
    "1.5b": ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
}
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

# ---- 切分 ----
CHUNK_SIZE = 400        # 每块最多字符数
CHUNK_OVERLAP = 60      # 相邻块重叠字符数

# ---- 检索 ----
CANDIDATES = 20         # 每路检索召回数量
TOP_K = 4               # 最终送给模型的资料段数
RRF_K = 60              # RRF 融合常数
MAX_CONTEXT_CHARS = 1800  # 送给模型的资料总字数上限（小模型少而精效果更好）

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
    return load_settings().get("size", "1.5b")

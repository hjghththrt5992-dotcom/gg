"""下载模型。国内网络访问不了 huggingface.co 时，自动改用镜像 hf-mirror.com。"""
from __future__ import annotations

import os
import urllib.request

from config import EMBED_MODEL, GGUF_MODELS, LLM_MODELS, RERANK_MODEL, model_dir

ENDPOINTS = {"hf": "https://huggingface.co", "mirror": "https://hf-mirror.com"}
WEIGHT_PATTERNS = ["*.json", "*.txt", "*.model", "*.safetensors", "tokenizer*"]


def pick_endpoint(source: str = "auto") -> str:
    if os.environ.get("HF_ENDPOINT"):
        return os.environ["HF_ENDPOINT"]
    if source in ENDPOINTS:
        return ENDPOINTS[source]
    try:
        urllib.request.urlopen(f"{ENDPOINTS['hf']}/api/models/{EMBED_MODEL}", timeout=5)
        return ENDPOINTS["hf"]
    except OSError:
        print("  huggingface.co 无法访问，改用国内镜像 hf-mirror.com")
        return ENDPOINTS["mirror"]


def download_repo(repo_id: str, endpoint: str) -> None:
    from huggingface_hub import snapshot_download

    target = model_dir(repo_id)
    print(f"  下载 {repo_id} → {target}")
    snapshot_download(repo_id, local_dir=str(target), endpoint=endpoint, allow_patterns=WEIGHT_PATTERNS)
    if not any(target.glob("*.safetensors")):  # 老模型只有 .bin 格式的权重
        snapshot_download(repo_id, local_dir=str(target), endpoint=endpoint, allow_patterns=["*.bin"])


def download_file(repo_id: str, filename: str, endpoint: str) -> None:
    from huggingface_hub import hf_hub_download

    target = model_dir(repo_id)
    print(f"  下载 {repo_id}/{filename} → {target}")
    hf_hub_download(repo_id, filename, local_dir=str(target), endpoint=endpoint)


def download(size: str, gguf: bool = False, rerank: bool = False, source: str = "auto",
             extra_sizes: tuple[str, ...] = ()) -> None:
    endpoint = pick_endpoint(source)
    print(f"[下载] 来源 {endpoint}")
    download_repo(EMBED_MODEL, endpoint)
    for s in dict.fromkeys((size, *extra_sizes)):
        download_repo(LLM_MODELS[s], endpoint)
    if gguf:
        download_file(*GGUF_MODELS[size], endpoint)
    if rerank:
        download_repo(RERANK_MODEL, endpoint)
    print("[下载] 完成")

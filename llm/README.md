# 低成本知识库问答模型

用开源小模型（Qwen2.5 0.5B / 1.5B）加本地知识库，做一个**普通电脑就能运行和微调**的问答系统。不需要显卡，不调用任何收费接口，数据全部留在本地。

**核心思路：小模型只负责"读懂资料、组织语言"，知识放在外挂知识库里。**这样小模型也能答得准，更新知识不用重新训练。

```
问题 ──► 混合检索（BM25 关键词 + bge 向量，RRF 融合，可选重排）──► 最相关的 3~5 段资料
                                                                        │
答案 + 引用来源 ◄── 小模型（4bit 量化 / LoRA 微调）按资料作答 ◄─────────┘
```

## 快速开始

需要 Python 3.9 及以上版本。在项目根目录执行：

```bash
pip install -r llm/requirements.txt        # 国内可加：-i https://pypi.tuna.tsinghua.edu.cn/simple
python llm/main.py check                   # 检测配置、测算力、推荐模型大小
python llm/main.py download                # 下载模型；huggingface.co 连不上时自动改用 hf-mirror.com
python llm/main.py build                   # 构建知识库索引
python llm/main.py chat                    # 命令行问答
python llm/main.py web                     # 网页问答，浏览器打开 http://127.0.0.1:8000
```

**有 NVIDIA 显卡？**先按 [PyTorch 官网](https://pytorch.org/get-started/locally/) 安装 CUDA 版 PyTorch，程序会自动用显卡。

**想更快、更省内存？**`pip install llama-cpp-python`，然后运行 `python llm/main.py download --gguf`，程序会自动改用 4bit 量化模型。

## 换成你自己的知识库

把文档放进 `llm/kb/docs/`（可以建子文件夹），支持 **md / txt / html / pdf / docx** 格式，然后重新运行 `python llm/main.py build`。自带的示例知识库是 13 篇"大模型基础知识 + 本项目使用手册"，可以直接删掉。

- 用 Markdown 标题（`#`、`##`）组织内容，检索效果最好
- 重建索引时，没变的内容会复用缓存的向量，速度很快
- 建议照 `llm/kb/eval.jsonl` 的格式，写几十道自己的评测题

## 微调（可选）

不微调也能用。微调能让小模型更会"按资料答题"：不被无关资料带偏、会标引用、资料里没有答案时如实说明。用的方法是 **RAFT**（检索增强微调）+ **LoRA**，只训练约 0.5% 的参数。

```bash
python llm/main.py gen-qa                  # 1. 让模型根据每段资料出题（自动过滤不靠谱的题）
python llm/main.py build-train             # 2. 做成训练样本：正确资料 + 干扰资料，另有 20% 拒答样本
python llm/main.py train --max-samples 50  # 3a. 先小规模试跑几分钟，确认 loss 在下降
python llm/main.py train                   # 3b. 正式训练；中途断了用 --resume 接着训练
python llm/main.py eval                    # 4. 对比微调前后的效果
python llm/main.py eval --finetuned
python llm/main.py chat --finetuned        # 5. 使用微调后的模型
```

出题的质量决定微调的效果：出题模型越大越好。有显卡或时间充裕时可以用 `gen-qa --size 1.5b`，甚至用 `--model` 指定更大的模型（如 Qwen2.5-7B-Instruct）。出题速度约为每段资料 10～30 秒，资料很多时可以先用 `--limit 300` 只处理一部分；中断后再次运行会接着处理。

想用 llama.cpp 运行微调后的模型：先运行 `python llm/main.py merge`，再按屏幕提示转成 GGUF。

## 需要什么配置

| | 最低 | 推荐 |
|---|---|---|
| CPU | 4 核，支持 AVX2（2013 年以后的大多数 CPU） | 8 核以上 |
| 内存 | 8GB（可问答、可微调 0.5B） | 16GB（可微调 1.5B） |
| 显卡 | 不需要 | NVIDIA 显卡，显存 6GB 以上，训练快 10 倍以上 |
| 硬盘 | 5GB | 10GB |

在一台 4 核的云服务器 CPU 上实测（不用显卡）：

| 项目 | 0.5B | 1.5B |
|---|---|---|
| LoRA 微调速度 | 约 150 token/秒 | 约 44 token/秒 |
| 微调 1000 条样本（1 轮） | 约 2 小时 | 约 7 小时 |
| LoRA 微调峰值内存 | 约 4GB | 约 8.5GB |
| 问答生成速度（transformers，FP32） | 约 21 token/秒 | 约 7 token/秒 |

用 llama.cpp 运行 4bit 量化模型，生成速度通常还能再快 2～4 倍。

你电脑上的实际时间，运行 `python llm/main.py check` 会根据实测算力给出估算。

## 命令一览

| 命令 | 作用 | 常用参数 |
|---|---|---|
| `check` | 检测配置，推荐模型 | |
| `download` | 下载模型 | `--size 0.5b/1.5b` `--gguf` `--rerank` `--source mirror` |
| `build` | 构建知识库索引 | `--docs 文件夹` `--no-embed` |
| `ask "问题"` | 问一个问题 | 同 chat |
| `chat` / `web` | 命令行 / 网页问答 | `--size` `--finetuned` `--model 路径` `--rerank` |
| `gen-qa` | 自动出题 | `--per-chunk 2` `--limit N` `--model 更大的模型` |
| `build-train` | 生成训练样本 | `--neg-ratio 0.2` `--variants 2` |
| `train` | LoRA 微调 | `--max-samples` `--epochs` `--resume` |
| `merge` | 合并 LoRA | |
| `eval` | 评测 | `--retrieval-only` `--finetuned` `--limit N` |

## 目录结构

```
llm/
├── main.py            统一入口
├── config.py          路径、模型名称、检索参数
├── kb/docs/           知识库文档（自带示例，可替换）
├── kb/eval.jsonl      评测题（63 道可回答 + 12 道知识库外的问题）
├── kb_builder/        文档读取、切分、BM25、向量化、构建索引
├── retriever/         混合检索、RRF 融合、重排
├── serve/             提示词、推理后端（llama.cpp / transformers）、命令行和网页界面
├── finetune/          出题、RAFT 样本、LoRA 训练、合并
├── evaluation/        评测
├── prepare/           配置检测、模型下载
└── data/              生成的文件：模型、索引、训练结果（不进 git，删了可以重新生成）
```

## 常见问题

**回答太慢？**换 0.5B（`--size 0.5b`），或者安装 llama-cpp-python 并运行 `download --gguf`。

**回答不准？**先运行 `eval --retrieval-only` 看检索命中率。命中率低就是检索的问题：给文档加上标题结构，或者用 `--rerank`。命中率高但答错，就换更大的模型或者微调。

**总说"知识库中未找到相关信息"？**这是防止瞎编的设计，说明检索到的资料里没有答案。检查一下知识库里有没有相关内容。

**Windows 装 llama-cpp-python 失败？**可以跳过，程序会自动改用 transformers，只是速度慢一些。

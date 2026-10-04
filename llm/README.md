# 低成本知识库训练模型

把**你自己的知识库**教给一个开源小模型（Qwen2.5 0.5B / 1.5B）。训练完成后，模型不查任何资料，直接回答知识库里的问题。**普通电脑就能训练**，不需要显卡，不调用任何收费接口，数据全部留在本地。

## 原理

知识库只是训练材料。只让模型读几遍原文，它往往能背出原文，被提问时却答不上来。研究发现（Allen-Zhu & Li，*Physics of Language Models*），**同一条知识要以多种不同的说法出现**，模型才能真正学会。所以训练数据这样做：

```
知识库文档 ──切分──► 段落 ──┬──► 原文（整段学习，相当于"读书"）
                            ├──► 改写 ×2~4（通俗讲解 / 要点笔记 / 换句式 / 百科式，同一知识多种说法）
                            ├──► 问答 ×3（被问到时怎么回答）
                            └──► 主题回忆（"请介绍 XX" → 该小节内容）
                                        │
                     混合成训练集 ──► LoRA 训练（秩 64，3 轮）──► 学会了知识的模型
```

- 改写和问答由底座模型自动生成，并自动过滤：不能编造原文没有的数字，不能跑题，答案必须能在原文中找到依据
- 留出 10% 的问答不参与训练，用来检验模型是真的学会了知识，还是只背住了训练题
- LoRA 只训练约 2%～4% 的参数，CPU 也能跑，对模型原有能力的影响也小

## 快速开始

需要 Python 3.9 及以上版本。在项目根目录执行：

```bash
pip install -r llm/requirements.txt        # 国内可加：-i https://pypi.tuna.tsinghua.edu.cn/simple
python llm/main.py check                   # 检测配置、测算力、推荐模型大小、估算训练时间
python llm/main.py download                # 下载底座模型；连不上 huggingface.co 时自动用 hf-mirror.com
python llm/main.py auto                    # 一键：切分 → 改写 → 出题 → 训练集 → 训练
python llm/main.py chat                    # 命令行问答（自动使用训练好的模型）
python llm/main.py web                     # 网页问答，浏览器打开 http://127.0.0.1:8000
```

每一步都能断点续跑：中途关机后重新运行同一条命令，已完成的部分会跳过（训练加 `--resume`）。

**有 NVIDIA 显卡？**先按 [PyTorch 官网](https://pytorch.org/get-started/locally/) 安装 CUDA 版 PyTorch，程序会自动用显卡，训练快 10 倍以上。

**想让生成训练数据更快？**`pip install llama-cpp-python`，然后运行 `python llm/main.py download --gguf`。改写和出题会自动改用 4bit 量化模型，速度快 2～4 倍。

## 换成你自己的知识库

1. 把文档放进 `llm/kb/docs/`（可以建子文件夹），支持 **md / txt / html / pdf / docx**，然后删掉自带的示例文档
2. 运行 `python llm/main.py auto --rebuild`

自带的示例知识库是 13 篇"大模型基础知识 + 本项目使用手册"，以及 63 道针对它的评测题（`llm/kb/eval.jsonl`）。用 Markdown 标题（`#`、`##`）组织内容效果最好。

## 分步运行

`auto` 就是依次运行下面 5 步，也可以单独运行某一步、调整参数：

```bash
python llm/main.py build                   # 1. 切分文档
python llm/main.py rewrite --limit 5       # 2. 改写（--limit 先试几段看看效果）
python llm/main.py rewrite                 #    全部改写，默认每段 2 种说法（--per-passage 最多 4）
python llm/main.py gen-qa                  # 3. 出题，默认每段 3 道（--per-passage）
python llm/main.py build-train             # 4. 混合成训练集，并预估训练时间
python llm/main.py train --max-samples 50  # 5a. 先小规模试跑几分钟，确认 loss 在下降
python llm/main.py train                   # 5b. 正式训练，默认 3 轮
```

**训练数据的质量决定效果。**用来改写和出题的模型越大越好：可以训练 0.5B，但用 `rewrite --size 1.5b`、`gen-qa --size 1.5b` 生成数据；甚至用 `--model` 指定更大的模型（比如 Qwen2.5-7B-Instruct 的 GGUF 文件）。也可以用任何方式（比如其他大模型）生成数据，按 `llm/data/corpus/` 里的格式放进去。

## 评测效果

```bash
python llm/main.py eval --base             # 训练前：原版底座模型闭卷答题
python llm/main.py eval                    # 训练后：同样的题再测一次
```

评测时不提供任何资料（闭卷）。测两套题：自带的 `kb/eval.jsonl` 和训练时自动留出的问答，每道题的回答都保存在 `llm/data/output/`。

**模型答错或记不住？**依次尝试：增加改写种类（`rewrite --per-passage 4`）、多出题（`gen-qa --per-passage 5`）、多训练几轮（`train --epochs 5`）、换用 1.5B、用更大的模型生成训练数据。

## 需要什么配置

| | 最低 | 推荐 |
|---|---|---|
| CPU | 4 核，支持 AVX2（2013 年以后的大多数 CPU） | 8 核以上 |
| 内存 | 8GB（可训练 0.5B） | 16GB（可训练 1.5B） |
| 显卡 | 不需要 | NVIDIA 显卡，显存 8GB 以上 |
| 硬盘 | 5GB | 10GB |

在一台 4 核的云服务器 CPU 上实测（不用显卡，模型结构与 Qwen2.5 相同）：

| 项目 | 0.5B | 1.5B |
|---|---|---|
| LoRA 训练速度 | 约 150 词元/秒 | 约 44 词元/秒 |
| 训练峰值内存 | 约 4GB | 约 8.5GB |
| 生成速度（transformers，FP32） | 约 21 词元/秒 | 约 7 词元/秒 |

以自带示例知识库（1.6 万字，70 段）为例：训练集约 8～12 万词元/轮，0.5B 训练 3 轮约 1 小时；生成训练数据（改写 + 出题）0.5B 约半小时到 1 小时，1.5B 约 2 小时，用 llama.cpp 能快 2～4 倍。`check` 和 `build-train` 会根据你电脑的实测算力估算训练时间。

## 命令一览

| 命令 | 作用 | 常用参数 |
|---|---|---|
| `check` | 检测配置，推荐模型，估算时间 | |
| `download` | 下载底座模型 | `--size 0.5b/1.5b` `--gguf` `--source mirror` |
| `build` | 1. 切分文档 | `--docs 文件夹` |
| `rewrite` | 2. 改写 | `--per-passage 1~4` `--limit N` `--size` `--model` |
| `gen-qa` | 3. 出题 | `--per-passage 3` `--limit N` `--size` `--model` |
| `build-train` | 4. 生成训练集 | `--eval-ratio 0.1` |
| `train` | 5. LoRA 训练 | `--epochs 3` `--rank 64` `--max-samples N` `--resume` |
| `auto` | 一键完成 1~5 | `--rebuild` `--rewrites 2` `--qa 3` `--epochs 3` |
| `ask "问题"` / `chat` / `web` | 问答 | `--base`（用原版模型）`--model 路径` |
| `eval` | 闭卷评测 | `--base` `--file` `--limit N` |
| `merge` | 合并 LoRA 得到完整模型 | |

想用 llama.cpp 运行训练好的模型：先 `merge`，再按屏幕提示转成 GGUF，然后 `chat --model xxx.gguf`。

## 目录结构

```
llm/
├── main.py            统一入口
├── config.py          路径、模型名称、训练参数
├── kb/docs/           知识库文档：训练材料（自带示例，可替换）
├── kb/eval.jsonl      示例知识库的评测题
├── kb_builder/        文档读取（md/txt/html/pdf/docx）、切分
├── finetune/          synth.py 改写和出题、build_data.py 混合训练集、train_lora.py 训练、merge.py 合并
├── serve/             推理后端（transformers / llama.cpp）、命令行和网页界面
├── evaluation/        闭卷评测
├── prepare/           配置检测、模型下载
└── data/              生成的文件：模型、训练数据、训练结果（不进 git，删了可以重新生成）
```

## 要知道的局限

- 把知识写进参数比查资料更容易出错：小模型可能记混相近的知识，或者对没学过的问题编造答案。知识越多，越需要更大的模型、更多改写和更多轮训练
- 知识库有改动时需要重新生成数据并训练
- 训练数据由底座模型自动生成，0.5B 生成的题目质量一般；条件允许时用更大的模型生成

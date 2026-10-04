#!/usr/bin/env bash
# 一键安装（Linux / macOS）：在项目根目录创建虚拟环境 .venv 并安装依赖。
# 用法：bash llm/setup.sh
# 可选环境变量：PYTHON=python3.11（指定 Python）  PIP_INDEX_URL=...（更换 pip 镜像）
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "找不到 $PY，请先安装 Python 3.9 或更高版本。"
  exit 1
fi

if [ ! -x .venv/bin/pip ]; then
  echo "[1/3] 创建虚拟环境 .venv"
  rm -rf .venv
  if ! "$PY" -m venv .venv; then
    rm -rf .venv
    echo
    echo "创建虚拟环境失败。Ubuntu / Debian 请先运行：sudo apt install python3-venv python3-full"
    exit 1
  fi
fi
PIP=".venv/bin/python -m pip"
$PIP install --upgrade pip -i "$INDEX" -q

echo "[2/3] 安装 PyTorch"
if command -v nvidia-smi >/dev/null 2>&1 || [ "$(uname)" = "Darwin" ]; then
  $PIP install torch -i "$INDEX"
else
  # 没有 NVIDIA 显卡：装只含 CPU 的版本，比默认版本小约 2GB；下载失败就改用默认版本
  $PIP install torch --index-url https://download.pytorch.org/whl/cpu || $PIP install torch -i "$INDEX"
fi

echo "[3/3] 安装其他依赖"
$PIP install -r llm/requirements.txt -i "$INDEX"

echo
echo "安装完成。之后每次打开新终端，先在项目根目录运行："
echo "  source .venv/bin/activate"
echo "然后就可以使用："
echo "  python llm/main.py check"

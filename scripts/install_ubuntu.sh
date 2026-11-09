#!/usr/bin/env bash
# 小窝：Ubuntu 安装。建虚拟环境、装依赖、生成 home.yaml。可以重复运行。
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p data
if [ ! -f home.yaml ]; then
  cp home.example.yaml home.yaml
  echo "已生成 home.yaml，按需修改住户和接入方式"
fi
echo "装好了。试运行：scripts/run_home.sh --mock --fast"

#!/usr/bin/env bash
# 启动小窝。常用参数：
#   --mock      模拟住户，不调用模型、不花额度
#   --fast      时间加速（分钟当秒用），试运行时看得快
#   --bind IP   监听地址，默认 127.0.0.1；局域网访问用 0.0.0.0，要先设 access_token
#   --hub URL   连外部控制台中枢（默认不连）
#   --port N    端口，默认取 home.yaml 的 port（8760）
cd "$(dirname "$0")/.."
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
# API key 等环境变量放在 ~/.config/cozy-home.env（每行 KEY=值），有就自动读
[ -f "$HOME/.config/cozy-home.env" ] && set -a && . "$HOME/.config/cozy-home.env" && set +a
exec "$PY" home/server.py "$@"

#!/bin/sh
# 容器入口: 初始化数据库(建表) -> (可选)写入演示数据 -> 启动服务。
set -e

echo "[entrypoint] 初始化数据库: ${DB_PATH:-/data/tides.db}"
python3 -m app.seed

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
echo "[entrypoint] 启动 uvicorn: http://${HOST}:${PORT}"
exec python3 -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"

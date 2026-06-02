#!/usr/bin/env bash
# douyin-im-grabber · 一键运行脚本
#
# 用法:
#   ./scripts/grab.sh --group "你的群名" --mode full
#   ./scripts/grab.sh --conv-id 1234567890 --mode incremental
#   ./scripts/grab.sh --group "xxx" --distill-only
#
# 自动定位 grab.py 路径，支持任意 cwd。

set -e

# 找仓库根目录（这个脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Python 解释器优先级：环境变量 > 当前 python3 > Hermes venv
PYTHON="${PYTHON:-python3}"

# 检查依赖
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "❌ 找不到 $PYTHON，请先安装 Python 3.10+"
  exit 1
fi

# 检查 grab.py 存在
GRAB_PY="$REPO_ROOT/src/douyin_im_grabber/grab.py"
if [[ ! -f "$GRAB_PY" ]]; then
  echo "❌ 找不到 $GRAB_PY"
  echo "   请确认你在 douyin-im-grabber 仓库根目录运行此脚本"
  exit 1
fi

# 检查依赖包
if ! "$PYTHON" -c "import requests, websocket" 2>/dev/null; then
  echo "⚠️  缺少依赖包，运行: pip install -r $REPO_ROOT/requirements.txt"
  exit 1
fi

# 跑
echo "📥 douyin-im-grabber"
echo "   脚本: $GRAB_PY"
echo "   参数: $*"
echo

exec "$PYTHON" "$GRAB_PY" "$@"

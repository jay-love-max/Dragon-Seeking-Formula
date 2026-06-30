#!/bin/bash
set -euo pipefail

# A-share Daily Post-Market Recap & 1-to-2 Board Relay Analysis

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== A-share Daily Recap Engine ==="
echo "Date: $(date +'%Y-%m-%d %H:%M:%S')"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    # 优先用仓库 venv(含 sklearn 等依赖),避免系统 python3 缺依赖导致 import 崩溃
    if [[ -x "$DIR/.venv/bin/python3" ]]; then
        PYTHON_BIN="$DIR/.venv/bin/python3"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    else
        PYTHON_BIN="$(command -v python)"
    fi
fi

# 关键依赖预检:sklearn 在 recap_engine 顶部 import,缺失会令整条管道在
# import 阶段崩溃(2026-06-29 cron 故障根因)。提前 fail 并给出可操作提示。
if ! "$PYTHON_BIN" -c "import sklearn" >/dev/null 2>&1; then
    echo "[gate] python ($PYTHON_BIN) 缺少 sklearn,复盘无法运行。" >&2
    echo "[gate] 请激活仓库 venv: source .venv/bin/activate 或设 PYTHON_BIN" >&2
    exit 1
fi

"$PYTHON_BIN" src/recap_engine.py "$@"
echo "Done!"

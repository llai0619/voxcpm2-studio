#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${VOXCPM_PROJECT_DIR:-$HOME/voxcpm2-studio}"
PYTHON_BIN="${VOXCPM_PYTHON:-$HOME/miniforge3/envs/voxcpm2/bin/python3.11}"
HOST="${VOXCPM_HOST:-127.0.0.1}"
PORT="${VOXCPM_PORT:-8808}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "[錯誤] 找不到 VoxCPM2 Python：$PYTHON_BIN" >&2
    echo "可設定 VOXCPM_PYTHON 指向 Python 3.10–3.12 執行檔。" >&2
    exit 1
fi

cd "$PROJECT_DIR"

"$PYTHON_BIN" -c '
import sys
if not ((3, 10) <= sys.version_info[:2] < (3, 13)):
    raise SystemExit(f"需要 Python 3.10–3.12，目前為 {sys.version.split()[0]}")
import voxcpm
print(f"VoxCPM：{voxcpm.__file__}")
'

echo "檢查 Web 介面相依套件……"
"$PYTHON_BIN" -m pip install --disable-pip-version-check -r requirements-web.txt

echo "啟動 VoxCPM2 Studio：http://$HOST:$PORT"
exec "$PYTHON_BIN" server.py --host "$HOST" --port "$PORT"

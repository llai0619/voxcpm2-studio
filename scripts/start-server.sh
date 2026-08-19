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
PROJECT_DIR="$(pwd -P)"

"$PYTHON_BIN" -c '
import sys
if not ((3, 10) <= sys.version_info[:2] < (3, 13)):
    raise SystemExit(f"需要 Python 3.10–3.12，目前為 {sys.version.split()[0]}")
import voxcpm
print(f"VoxCPM：{voxcpm.__file__}")
'

echo "檢查 Web 介面相依套件……"
"$PYTHON_BIN" -m pip install --disable-pip-version-check -r requirements-web.txt

existing_pids=()
for process_dir in /proc/[0-9]*; do
    [[ -r "$process_dir/cmdline" && -L "$process_dir/cwd" ]] || continue
    process_cwd="$(readlink -f "$process_dir/cwd" 2>/dev/null || true)"
    [[ "$process_cwd" == "$PROJECT_DIR" ]] || continue
    process_command="$(tr '\0' ' ' < "$process_dir/cmdline" 2>/dev/null || true)"
    [[ "$process_command" == *"server.py"* ]] || continue
    process_pid="${process_dir##*/}"
    [[ "$process_pid" != "$$" ]] || continue
    existing_pids+=("$process_pid")
done

if (( ${#existing_pids[@]} )); then
    echo "停止舊版 VoxCPM2 Studio（PID：${existing_pids[*]}）……"
    kill -TERM "${existing_pids[@]}" 2>/dev/null || true
    still_running=0
    for _ in {1..20}; do
        still_running=0
        for process_pid in "${existing_pids[@]}"; do
            if kill -0 "$process_pid" 2>/dev/null; then
                still_running=1
            fi
        done
        (( still_running == 0 )) && break
        sleep 0.25
    done
    if (( still_running )); then
        echo "[錯誤] 舊服務未能正常停止，請手動結束 PID：${existing_pids[*]}" >&2
        exit 1
    fi
fi

export VOXCPM_BUILD="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "啟動 VoxCPM2 Studio：http://$HOST:$PORT"
exec "$PYTHON_BIN" server.py --host "$HOST" --port "$PORT"

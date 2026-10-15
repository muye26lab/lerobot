#!/usr/bin/env bash
set -euo pipefail
cd /home/yuxun/workspace/lerobot
export MUJOCO_GL=egl HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
exec /home/yuxun/.local/bin/uv run --no-sync python -u examples/pi05_local/runtime.py "$@"

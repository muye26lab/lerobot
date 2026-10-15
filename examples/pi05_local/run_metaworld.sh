#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export MUJOCO_GL=egl
exec "$HOME/.local/bin/uv" run --no-sync python -u -m examples.pi05_local.metaworld_sft \
  --output "outputs/pi05-metaworld-$(date +%Y%m%d-%H%M%S)" "$@"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export RERUN_ANALYTICS_ENABLED=false
"$HOME/.local/bin/uv" run --no-sync python -m examples.pi05_local.dashboard start
exec bash examples/pi05_local/run_metaworld.sh --visualize \
  --rerun-grpc rerun+http://127.0.0.1:18766/proxy --tasks reach-v3 --seeds 0 "$@"

param([ValidateSet('start', 'status', 'stop')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
wsl.exe -d Ubuntu-24.04 -- /home/yuxun/.local/bin/uv run --no-sync --directory /home/yuxun/workspace/lerobot python -m examples.pi05_local.dashboard $Action
exit $LASTEXITCODE

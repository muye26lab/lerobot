$ErrorActionPreference = 'Stop'
wsl.exe -d Ubuntu-24.04 -- bash /home/yuxun/workspace/lerobot/examples/pi05_local/run_visual.sh @args
exit $LASTEXITCODE

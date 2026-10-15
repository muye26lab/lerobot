"""Start/stop local-only Rerun and TensorBoard services in WSL."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "outputs/pi05-dashboard"


def alive(service: dict) -> bool:
    try:
        command = Path(f"/proc/{service['pid']}/cmdline").read_bytes().split(b"\0")
        return all(str(part).encode() in command for part in service["command"])
    except FileNotFoundError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"])
    parser.add_argument("--recording", type=Path, help="RRD to preload when starting a new Rerun server")
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    state_path = STATE / "services.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args.action == "stop":
        for service in state.values():
            if alive(service):
                os.kill(service["pid"], signal.SIGTERM)
        print("Stopped dashboard services owned by this launcher.")
        return
    commands = {
        "rerun": [
            str(Path(sys.executable).with_name("rerun")),
            "--serve-web",
            "--bind",
            "127.0.0.1",
            "--port",
            "18766",
            "--web-viewer-port",
            "9090",
            "--server-memory-limit",
            "512MiB",
        ],
        "tensorboard": [
            str(Path(sys.executable).with_name("tensorboard")),
            "--logdir",
            str(ROOT / "outputs"),
            "--host",
            "127.0.0.1",
            "--port",
            "6006",
            "--load_fast",
            "false",
        ],
    }
    if args.recording:
        if not args.recording.is_file():
            parser.error("Recording does not exist")
        commands["rerun"].append(str(args.recording.resolve()))
    ports = {"rerun": [9090, 18766], "tensorboard": [6006]}
    for name, command in commands.items():
        if args.action == "start" and not (name in state and alive(state[name])):
            for port in ports[name]:
                with socket.socket() as probe:
                    try:
                        probe.bind(("127.0.0.1", port))
                    except OSError as exc:
                        raise RuntimeError(
                            f"Port {port} is occupied; existing service left untouched"
                        ) from exc
            env = dict(os.environ, RERUN_ANALYTICS_ENABLED="false")
            with (STATE / f"{name}.log").open("ab") as log:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            state[name] = {"pid": process.pid, "command": command}
            state_path.write_text(json.dumps(state, indent=2))
        url = f"http://localhost:{ports[name][0]}"
        ready = False
        for _ in range(40 if args.action == "start" else 1):
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    ready = response.status == 200
                break
            except OSError:
                time.sleep(0.25)
        print(f"{name}: {'ready' if ready else 'not ready'} {url}")
        if name == "rerun" and ready:
            print("Viewer: http://localhost:9090/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A18766%2Fproxy")
        if args.action == "start" and not ready:
            raise RuntimeError(f"Inspect {STATE / (name + '.log')}")


if __name__ == "__main__":
    main()

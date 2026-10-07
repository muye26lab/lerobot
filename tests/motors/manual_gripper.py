"""Manually test a small opening/closing cycle of SO-101 gripper ID 6.

Run in an environment with LeRobot's Feetech extra installed::

    python tests/motors/manual_gripper.py

The default port is /dev/cu.wchusbserial5CE51155781; override it with --port.

Keep fingers and objects clear of the gripper. This script moves the motor by
200 encoder ticks (about 18 degrees), then returns near its initial position.
It requires position mode, valid stored limits, and torque initially disabled.
The script disables torque on exit and restores the original torque limit,
velocity, and acceleration if communication remains available. It does not
change calibration or IDs, and is not collected as an automated pytest test.
"""

import argparse
import time

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        default="/dev/cu.wchusbserial5CE51155781",
        help="Serial port of the SO-101 arm (gripper ID 6; default: %(default)s)",
    )
    args = parser.parse_args()
    bus = FeetechMotorsBus(
        args.port,
        {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)},
    )
    saved: dict[str, int] = {}
    modified = False

    def read(name: str) -> int:
        return int(bus.read(name, "gripper", normalize=False, num_retry=2))

    def write(name: str, value: int) -> None:
        bus.write(name, "gripper", value, normalize=False, num_retry=2)

    def move(target: int) -> None:
        write("Goal_Position", target)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            position = read("Present_Position")
            load = read("Present_Load")
            status = read("Status")
            if status or abs(load) > 200 or read("Present_Temperature") >= 60:
                raise RuntimeError(f"Stopped: position={position}, load={load}, status={status}")
            if abs(position - target) <= 15:
                print(f"Reached target={target}, measured={position}, load={load}", flush=True)
                return
            time.sleep(0.1)
        raise RuntimeError(f"Movement timed out: target={target}, measured={position}")

    try:
        bus._connect(handshake=False)
        if read("Model_Number") != 777 or read("Operating_Mode") != 0:
            raise RuntimeError("Expected STS3215 in position mode")
        if read("Torque_Enable") != 0 or read("Status") != 0:
            raise RuntimeError("Expected idle gripper with torque disabled and no status errors")
        start = read("Present_Position")
        low, high = read("Min_Position_Limit"), read("Max_Position_Limit")
        if not (0 <= low <= start <= high <= 4095) or high - low < 300:
            raise RuntimeError(f"Unexpected limits: {low=}, {start=}, {high=}")
        if read("Present_Temperature") >= 60:
            raise RuntimeError("Motor temperature too high for test")
        target = start + 200 if high - start >= start - low else start - 200
        if not low + 20 <= target <= high - 20:
            raise RuntimeError("Insufficient room for test")
        for name in ["Torque_Limit", "Goal_Velocity", "Acceleration"]:
            saved[name] = read(name)
        modified = True
        write("Torque_Limit", min(saved["Torque_Limit"], 150))
        write("Goal_Velocity", 100)
        write("Acceleration", 10)
        write("Goal_Position", start)
        write("Torque_Enable", 1)
        print(f"Testing ID 6: {start} -> {target} -> {start}", flush=True)
        move(target)
        time.sleep(0.5)
        move(start)
        print("Small movement cycle completed", flush=True)
    finally:
        if bus.port_handler.is_open:
            try:
                if modified:
                    write("Torque_Enable", 0)
                    print("Torque disabled", flush=True)
                    for name, value in saved.items():
                        write(name, value)
                    print(
                        f"Final position={read('Present_Position')}; torque={read('Torque_Enable')}",
                        flush=True,
                    )
            finally:
                bus.port_handler.closePort()


if __name__ == "__main__":
    main()

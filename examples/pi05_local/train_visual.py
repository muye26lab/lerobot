"""Run an existing LeRobot training configuration with local TensorBoard metrics.

No training configuration or dataset is created automatically. This wrapper observes
structured MetricsTracker log records and leaves optimizer/model behavior unchanged.
"""

import argparse
import logging
import math
import re
import sys
from pathlib import Path
from typing import Any

from lerobot.utils.logging_utils import MetricsTracker


class TrainingMetricsHandler(logging.Handler):
    def __init__(self, directory: str):
        from torch.utils.tensorboard import SummaryWriter

        super().__init__(logging.INFO)
        self.writer = SummaryWriter(directory, flush_secs=2)
        self.finished = False

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, MetricsTracker):
            values = record.msg.to_dict()
            step = int(values["steps"])
            for name, value in values.items():
                if isinstance(value, (int, float)) and math.isfinite(value):
                    self.writer.add_scalar(f"train/{name}", value, step)
        elif isinstance(record.msg, str):
            match = re.fullmatch(r"step (\d+): eval_loss=([\d.eE+\-]+)", record.getMessage())
            if match:
                self.writer.add_scalar("validation/loss", float(match[2]), int(match[1]))

    def close(self) -> None:
        if not self.finished:
            self.writer.close()
            self.finished = True
        super().close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--tensorboard-dir", type=Path)
    args, training_args = parser.parse_known_args()
    if args.tensorboard_dir is None:
        parser.error(
            "Provide --tensorboard-dir outputs/<training-run>/tensorboard and normal LeRobot training arguments"
        )
    # Import only after CLI validation; training extras are independent of inference extras.
    from lerobot.scripts import lerobot_train

    original_logging = lerobot_train.init_logging
    handlers: list[TrainingMetricsHandler] = []

    def setup_logging(*init_args: Any, **init_kwargs: Any) -> None:
        original_logging(*init_args, **init_kwargs)
        accelerator = init_kwargs.get("accelerator")
        if accelerator is None or accelerator.is_main_process:
            handler = TrainingMetricsHandler(str(args.tensorboard_dir))
            logging.getLogger().addHandler(handler)
            handlers.append(handler)

    original_argv = sys.argv
    lerobot_train.init_logging = setup_logging
    sys.argv = [sys.argv[0], *training_args]
    try:
        lerobot_train.main()
    finally:
        sys.argv = original_argv
        lerobot_train.init_logging = original_logging
        for handler in handlers:
            logging.getLogger().removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    main()

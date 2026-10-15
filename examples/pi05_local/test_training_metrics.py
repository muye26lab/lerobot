import logging
import tempfile
import unittest

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

from examples.pi05_local.train_visual import TrainingMetricsHandler
from lerobot.utils.logging_utils import AverageMeter, MetricsTracker


class TrainingMetricsTests(unittest.TestCase):
    def test_structured_training_metrics_use_exact_step_and_average(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = TrainingMetricsHandler(directory)
            tracker = MetricsTracker(1, 20, 2, {"loss": AverageMeter("loss"), "lr": AverageMeter("lr")})
            tracker.loss = 2.0
            tracker.loss = 4.0
            tracker.lr = 0.001
            tracker.step()
            handler.emit(logging.LogRecord("root", logging.INFO, "test", 1, tracker, (), None))
            handler.emit(
                logging.LogRecord("root", logging.INFO, "test", 1, "step 7: eval_loss=1.2500", (), None)
            )
            handler.close()
            events = EventAccumulator(directory).Reload()
            self.assertEqual([(v.step, v.value) for v in events.Scalars("train/loss")], [(1, 3.0)])
            self.assertEqual([(v.step, v.value) for v in events.Scalars("validation/loss")], [(7, 1.25)])


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

from examples.pi05_local.telemetry import EpisodeTelemetry, capture_denoising


class TelemetryTests(unittest.TestCase):
    def test_trace_does_not_change_output_and_restores_method(self):
        class Model:
            def denoise_step(self, *, x_t, timestep):
                return x_t * timestep[:, None, None]

        model = Model()
        original = model.denoise_step
        x = torch.arange(20, dtype=torch.float32).reshape(1, 5, 4)
        t = torch.ones(1)
        expected = original(x_t=x, timestep=t)
        with capture_denoising(model) as trace:
            actual = model.denoise_step(x_t=x, timestep=t)
        torch.testing.assert_close(expected, actual, rtol=0, atol=0)
        self.assertEqual(model.denoise_step, original)
        self.assertEqual(len(trace), 1)
        np.testing.assert_array_equal(trace[0][1].numpy(), x[0].numpy())
        with self.assertRaisesRegex(RuntimeError, "test"), capture_denoising(model):
            raise RuntimeError("test")
        self.assertEqual(model.denoise_step, original)

    def test_real_recording_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with EpisodeTelemetry(out, "reach-v3", 0, "Reach", grpc_url=None) as telemetry:
                image = np.zeros((48, 48, 3), dtype=np.uint8)
                telemetry.observe(0, image, np.array([0, 0, 0.1, 1]))
                telemetry.transition(1, image + 100, np.array([0, 0, 0.2, 0]), np.ones(4), 3.0, True)
                telemetry.inference(0, np.zeros((5, 32)), [(1.0, torch.ones(5, 32))], 0.2)
                telemetry.finish(True, 1)
            recording = out / "reach-v3-seed0.rrd"
            self.assertGreater(recording.stat().st_size, 1000)
            event = EventAccumulator(str(out / "tensorboard" / "reach-v3-seed0")).Reload()
            values = event.Scalars("eval/reward")
            self.assertEqual([(v.step, v.value) for v in values], [(1, 3.0)])
            self.assertEqual(event.Scalars("eval/success")[0].value, 1)
            trace = np.load(out / "reach-v3-seed0-denoising.npz")
            self.assertEqual(trace["chunk_0_states"].shape, (2, 5, 32))
            np.testing.assert_allclose(trace["chunk_0_times"], [1, 0])


if __name__ == "__main__":
    unittest.main()

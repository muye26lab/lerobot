import tempfile
import unittest
from pathlib import Path

import bitsandbytes as bnb
import numpy as np
import torch
from safetensors.torch import load_file, save_file

from examples.pi05_local.runtime import NF4Linear, experimental_action, normalized_state


class AdapterTests(unittest.TestCase):
    def test_state_validation_and_padding(self):
        state = normalized_state(np.array([0.0, 0.5, 0.2, 0.8]))
        self.assertEqual(state.shape, (32,))
        self.assertTrue(np.all(state[4:] == 0))
        with self.assertRaises(ValueError):
            normalized_state(np.array([np.nan, 0, 0, 0]))
        with self.assertRaises(ValueError):
            normalized_state(np.zeros(3))

    def test_action_mapping_is_explicit(self):
        action = np.zeros(32)
        action[:3] = [2, -2, 0.25]
        action[3] = -0.8
        action[6] = 0.7
        np.testing.assert_allclose(experimental_action(action), [1, -1, 0.25, 0.7])
        action[0] = np.inf
        with self.assertRaises(ValueError):
            experimental_action(action)


@unittest.skipUnless(torch.cuda.is_available(), "CUDA required")
class QuantizationTests(unittest.TestCase):
    def test_nf4_numerics_and_serialization(self):
        torch.manual_seed(5)
        weight = torch.randn(128, 256, device="cuda", dtype=torch.bfloat16)
        x = torch.randn(4, 256, device="cuda", dtype=torch.bfloat16)
        layer = NF4Linear(
            256, 128, bias=False, compute_dtype=torch.bfloat16, quant_type="nf4", quant_storage=torch.bfloat16
        )
        layer.weight = bnb.nn.Params4bit(
            weight,
            requires_grad=False,
            quant_type="nf4",
            quant_storage=torch.bfloat16,
            compress_statistics=True,
            module=layer,
        ).to("cuda")
        with torch.inference_mode():
            expected = torch.nn.functional.linear(x, weight).float()
            actual = layer(x).float()
        self.assertTrue(torch.isfinite(actual).all())
        self.assertLess(float((actual - expected).norm() / expected.norm()), 0.15)
        self.assertEqual(layer.weight.dtype, torch.bfloat16)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quantized.safetensors"
            save_file({key: value.cpu() for key, value in layer.state_dict().items()}, str(path))
            state = load_file(str(path))
            restored = NF4Linear(
                256,
                128,
                bias=False,
                compute_dtype=torch.bfloat16,
                quant_type="nf4",
                quant_storage=torch.bfloat16,
            )
            restored.weight = bnb.nn.Params4bit.from_prequantized(
                state["weight"],
                {k: v for k, v in state.items() if k != "weight"},
                device="cuda",
                module=restored,
            )
            restored.quant_state = restored.weight.quant_state
            with torch.inference_mode():
                torch.testing.assert_close(restored(x).float(), actual, rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()

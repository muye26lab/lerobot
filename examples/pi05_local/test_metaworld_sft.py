import unittest

import numpy as np

from examples.pi05_local.metaworld_sft import action_from_quantiles, prompt_tokens, validate_stats
from examples.pi05_local.runtime import validate_artifact


class ProfileTests(unittest.TestCase):
    def test_action_quantiles_and_gripper(self):
        stats = {"q01": [-4, -3, -12, -1], "q99": [8, 7, 10, 1]}
        action = np.zeros(32, dtype=np.float32)
        action[:4] = [-1, 1, 0, 0.5]
        action[6] = -1
        raw, clipped = action_from_quantiles(action, stats)
        np.testing.assert_allclose(raw, [-4, 7.000001, -0.9999995, 0.50000075], atol=1e-6)
        np.testing.assert_allclose(clipped, [-1, 1, -0.9999995, 0.50000075], atol=1e-6)
        action[0] = np.nan
        with self.assertRaises(ValueError):
            action_from_quantiles(action, stats)

    def test_invalid_stats(self):
        for stats in ({"q01": [0], "q99": [1]}, {"q01": [0] * 4, "q99": [0] * 4}):
            with self.assertRaises(ValueError):
                validate_stats(stats)

    def test_prompt_has_no_discrete_state(self):
        class Tokenizer:
            def encode(self, text, add_bos=False):
                if add_bos:
                    self_text.append(text)
                    return [2, 17, 18]
                self_text.append(text)
                return [108]

        self_text = []
        tokens, mask = prompt_tokens("  reach_target\nnow  ", Tokenizer())
        self.assertEqual(self_text, ["reach target now", "\n"])
        self.assertEqual(tokens[:5], [2, 17, 18, 108, 0])
        self.assertEqual(sum(mask), 4)
        self.assertEqual(len(tokens), 200)

    def test_artifact_identity(self):
        manifest = {"source_revision": "sft", "profile": {"stats_sha256": "abc"}}
        validate_artifact(manifest, "sft", {"stats_sha256": "abc"})
        with self.assertRaises(ValueError):
            validate_artifact(manifest, "base", {"stats_sha256": "abc"})
        with self.assertRaises(ValueError):
            validate_artifact(manifest, "sft", {"stats_sha256": "other"})


if __name__ == "__main__":
    unittest.main()

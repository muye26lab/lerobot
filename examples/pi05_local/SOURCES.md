# Sources and deployment contract

The Meta-World profile uses public pretrained weights from
[RLinf/RLinf-Pi05-MetaWorld-SFT](https://huggingface.co/RLinf/RLinf-Pi05-MetaWorld-SFT/tree/60b2d0309af8bb087c9e9b250f8c7f9db50c0f8e),
revision `60b2d0309af8bb087c9e9b250f8c7f9db50c0f8e`.
The source checkpoint and `lerobot/metaworld_mt50/norm_stats.json` are cached unchanged.
No training or unrestricted pickle loading is performed.

The architecture comes from the local LeRobot PI05 implementation and the cached
`lerobot/pi05_base` config, revision `22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0`.
Only `chunk_size=5`, `n_action_steps=5`, `num_inference_steps=5` are overridden
in addition to the existing NF4 loader's precision/device settings.

The data contract and bundled `metaworld_prompts.json` come from the
[RLinf project](https://github.com/RLinf/RLinf/tree/0067f7d5ce525c18bda439ed8dbb638abafd6a06)
(Apache-2.0 code; copyright the RLinf contributors), particularly:

- `rlinf/models/embodiment/openpi/dataconfig/__init__.py`: `pi05_metaworld`,
  five-action horizon, `discrete_state_input=False`, no extra delta transform.
- `rlinf/models/embodiment/openpi/policies/metaworld_policy.py`: base camera,
  absent wrist views, output first four actions.
- `rlinf/envs/sim/metaworld/metaworld_config.json`: task prompts.
- `toolkits/standalone_eval_scripts/openpi/metaworld_eval.py`: camera position,
  image flips, 15 settling steps, five denoising steps, 160 policy steps.

Preprocessing follows [OpenPI](https://github.com/Physical-Intelligence/openpi)
(Apache-2.0): plain cleaned prompt + separately tokenized newline with BOS,
PIL bilinear uint8 resize, quantile unnormalization with epsilon `1e-6`.
The tokenizer is the official public
[Big Vision PaliGemma tokenizer](https://storage.googleapis.com/big_vision/paligemma_tokenizer.model),
SHA256 `8986bb4f423f07f8c7f70d0dbe3526fb2316056c17bae71b1ea975e77a168fc6`.
Artifact manifests bind source revision, config/statistics/tokenizer hashes and model overrides.
Evaluation reports also hash the task prompt file.

Local evaluation uses LeRobot's seeded Meta-World wrapper with MuJoCo 3.8.1 and
Meta-World 3.0.0. Its reset protocol and early success termination differ from
some upstream benchmarks. Results are local validation, not a reproduction of
the RLinf MT50 benchmark. Code licenses do not establish a separate model-weight
license; consult the source model repository before redistribution.

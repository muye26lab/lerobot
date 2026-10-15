# PI05 local inference and MuJoCo deployment

**Goal:** Run the downloaded PI05 checkpoint with NF4 weight quantization on the local RTX 5060 Ti, execute an offline Meta-World loop, and retain commands, video and measured resource usage.

**Architecture:** Isolated example entry point, meta-device construction, strict streaming checkpoint loading, bitsandbytes NF4 for language backbone linear layers, native LeRobot action inference, and Meta-World reach-v3 rendering. Preserve original weights. Base checkpoint actions are an explicitly experimental adapter, not a trained Meta-World policy.

**Tech stack:** WSL Ubuntu 24.04, uv, PyTorch CUDA 12.8, LeRobot PI05, bitsandbytes, MuJoCo, Meta-World.

1. Install locked pi/metaworld dependencies and a recorded bitsandbytes version. Validate CUDA and NF4 execution.
2. Verify tokenizer access; use an official published PaliGemma tokenizer if available, otherwise require user authentication. Cache all assets before offline execution.
3. Implement strict streaming NF4 loading. Verify checkpoint coverage and no meta tensors before inference. Preserve high precision action expert, norms, vision and embedding.
4. Implement input validation and explicitly named experimental state/action mapping. Test validation and quantized linear numerics before integration.
5. Run Meta-World render/step smoke test, then real pretrained model inference and at least two feedback cycles with ten denoising steps. Save video, actions, timings, memory and task outcome.
6. Repeat with network-disabled Hugging Face mode, document exact reproduction commands and limitations. No task success or precision parity claims without appropriate evidence.

## Approved continuation: task-matched Meta-World deployment

1. Use public RLinf PI05 Meta-World SFT revision `60b2d0309af8bb087c9e9b250f8c7f9db50c0f8e`
   and its quantile statistics. Preserve the original base deployment.
2. Match the published five-action horizon, plain prompt without discrete state,
   corner2 camera, PIL image resize, first four action dimensions and quantile unnormalization.
3. Bind the separate NF4 artifact to source revision and preprocessing assets;
   test action semantics and reject mixed artifacts.
4. Evaluate reach, push and pick-place with seeds 0, 1, 2, 160 policy steps each;
   retain every outcome, action trajectory, inference latency and video.
5. Reload under an isolated network namespace, compare the same seeded trajectory,
   and provide Windows/WSL launchers, source provenance and a measured local report.

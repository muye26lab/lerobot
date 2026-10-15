# PI05 local visualization implementation plan

**Goal:** Make the approved local Meta-World deployment observable in a local Rerun dashboard, MuJoCo interactive window, and TensorBoard metrics.

**Architecture:** Optional telemetry in the existing example, using dynamic timestamped camera frames and step-aligned state/action/reward logs. Each episode saves a standalone RRD and denoising arrays. Rerun provides camera, 3D measured end-effector path, action/state curves, predicted action chunk and intermediate denoising tensors. A passive MuJoCo viewer uses copied model/data to avoid user interaction modifying evaluation. Local TensorBoard shows real evaluation metrics and can read future training logs; do not fabricate training data or start PI05 training.

**Tech stack:** Existing WSL Python environment, pinned compatible rerun-sdk, TensorBoard, MuJoCo GLFW/WSLg, PyTorch, NumPy.

The user approved the proposed Rerun/MuJoCo/TensorBoard direction and requested implementation. Continue in the current example directory, preserve all previous results and existing repository changes; no separate approval or commit is required.

1. Install and inspect compatible visualization APIs. Verify WSLg and local browser endpoints; save dependency versions.
2. Add `telemetry.py`: per-episode recording, blueprint, dynamic image/state/action/metrics, measured 3D path, final predicted chunks, intermediate flow states, local TensorBoard writer. Add tests for timestep alignment, real RRD/TensorBoard serialization and trace capture restoring the model without changing outputs.
3. Extend `metaworld_sft.py` with optional recording/streaming/viewer arguments. Capture pre/post action states explicitly; trace denoise inputs without modifying numerics. Keep existing nonvisual execution behavior.
4. Add launch/replay commands for Windows and WSL and a persistent local dashboard service. Keep servers local; run one task by default for an accessible visual demo. Save recordings for later offline playback.
5. Run targeted tests, lint, real GPU inference with telemetry and a short MuJoCo viewer check. Compare the seeded complete episode to the previous baseline; verify recordings and HTTP services. Document overhead and limitations, including absent training runs.

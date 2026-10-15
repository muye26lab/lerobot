"""Offline RLinf PI05 Meta-World evaluation with the published OpenPI data contract."""

import argparse
import hashlib
import json
import os
import time
from contextlib import nullcontext
from pathlib import Path

import av
import numpy as np
import sentencepiece as spm
import torch
from PIL import Image

from examples.pi05_local.runtime import DEFAULT_ASSETS, DEFAULT_CHECKPOINT, load_policy, save_artifact
from examples.pi05_local.telemetry import EpisodeTelemetry, SimulationViewer, capture_denoising
from lerobot.policies.pi05 import PI05Policy
from lerobot.utils.constants import OBS_LANGUAGE_ATTENTION_MASK, OBS_LANGUAGE_TOKENS

REVISION = "60b2d0309af8bb087c9e9b250f8c7f9db50c0f8e"
REPO_ID = "RLinf/RLinf-Pi05-MetaWorld-SFT"
CHECKPOINT = (
    Path.home() / ".cache/huggingface/hub/models--RLinf--RLinf-Pi05-MetaWorld-SFT/snapshots" / REVISION
)
REFERENCE_REVISION = "0067f7d5ce525c18bda439ed8dbb638abafd6a06"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_stats(stats: dict) -> tuple[np.ndarray, np.ndarray]:
    low, high = (np.asarray(stats[key], dtype=np.float32) for key in ("q01", "q99"))
    if low.shape != (4,) or high.shape != (4,):
        raise ValueError("Expected four-dimensional Meta-World quantiles")
    if not np.isfinite(low).all() or not np.isfinite(high).all() or not np.all(high > low):
        raise ValueError("Invalid quantiles")
    return low, high


def action_from_quantiles(action: np.ndarray, stats: dict) -> tuple[np.ndarray, np.ndarray]:
    action = np.asarray(action, dtype=np.float32)
    if action.shape != (32,) or not np.isfinite(action).all():
        raise ValueError("Expected 32 finite action values")
    low, high = validate_stats(stats)
    raw = (action[:4] + 1) / 2 * (high - low + 1e-6) + low
    return raw, np.clip(raw, -1, 1)


def prompt_tokens(task: str, tokenizer: spm.SentencePieceProcessor) -> tuple[list[int], list[bool]]:
    cleaned = task.strip().replace("_", " ").replace("\n", " ")
    tokens = tokenizer.encode(cleaned, add_bos=True) + tokenizer.encode("\n")
    if len(tokens) > 200:
        raise ValueError("Prompt exceeds checkpoint context length")
    return tokens + [0] * (200 - len(tokens)), [True] * len(tokens) + [False] * (200 - len(tokens))


def prepare_batch(image: np.ndarray, task: str, tokenizer: spm.SentencePieceProcessor) -> dict:
    if image.shape != (480, 480, 3) or image.dtype != np.uint8:
        raise ValueError("Expected the Meta-World 480x480 RGB camera")
    # Match OpenPI's PIL bilinear uint8 resize, before float conversion.
    resized = np.array(Image.fromarray(image).resize((224, 224), Image.Resampling.BILINEAR))
    tokens, mask = prompt_tokens(task, tokenizer)
    return {
        "observation.images.base_0_rgb": torch.from_numpy(resized).permute(2, 0, 1)[None].cuda().float()
        / 255,
        # This checkpoint has no state projection and discrete_state_input=False.
        "observation.state": torch.zeros((1, 32), device="cuda"),
        OBS_LANGUAGE_TOKENS: torch.tensor([tokens], device="cuda"),
        OBS_LANGUAGE_ATTENTION_MASK: torch.tensor([mask], device="cuda"),
    }


def evaluate_episode(
    policy: PI05Policy,
    tokenizer: spm.SentencePieceProcessor,
    stats: dict,
    task: str,
    prompt: str,
    seed: int,
    steps: int,
    out: Path,
    visualize: bool = False,
    viewer: bool = False,
    rerun_grpc: str | None = None,
) -> dict:
    from lerobot.envs.metaworld import MetaworldEnv

    torch.manual_seed(seed)
    policy.reset()
    env = MetaworldEnv(task, obs_type="pixels_agent_pos")
    telemetry = EpisodeTelemetry(out, task, seed, prompt, rerun_grpc) if visualize else None
    sim_viewer = None
    video = av.open(str(out / f"{task}-seed{seed}.mp4"), "w")
    stream = video.add_stream("libx264", rate=20)
    stream.width, stream.height, stream.pix_fmt = 480, 480, "yuv420p"
    history, latencies = [], []
    success = False

    def record(image: np.ndarray) -> None:
        for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
            video.mux(packet)

    try:
        obs, _ = env.reset(seed=seed)
        for _ in range(15):
            obs, _, terminated, truncated, _ = env.step(np.zeros(4, dtype=np.float32))
            if terminated or truncated:
                raise RuntimeError("Episode ended during settling")
        if viewer:
            sim_viewer = SimulationViewer(env._env)
            sim_viewer.update(env._env)
        initial_state = obs["agent_pos"].tolist()
        if telemetry:
            telemetry.observe(0, obs["pixels"], obs["agent_pos"])
        for step in range(steps):
            record(obs["pixels"])
            if step % 5 == 0:
                batch = prepare_batch(obs["pixels"], prompt, tokenizer)
                torch.cuda.synchronize()
                start = time.perf_counter()
                trace_context = capture_denoising(policy.model) if telemetry else nullcontext([])
                with torch.inference_mode(), trace_context as denoise_trace:
                    chunk = policy.predict_action_chunk(batch).float().cpu().numpy()[0]
                torch.cuda.synchronize()
                latencies.append(time.perf_counter() - start)
                if chunk.shape != (5, 32) or not np.isfinite(chunk).all():
                    raise ValueError("Invalid predicted chunk")
                if telemetry:
                    telemetry.inference(step, chunk, denoise_trace, latencies[-1])
            raw, action = action_from_quantiles(chunk[step % 5], stats)
            obs, reward, terminated, truncated, info = env.step(action)
            success = success or bool(info["is_success"])
            if telemetry:
                telemetry.transition(
                    step + 1, obs["pixels"], obs["agent_pos"], action, float(reward), success
                )
            history.append(
                {
                    "step": step,
                    "action": action.tolist(),
                    "raw_action": raw.tolist(),
                    "normalized_action": chunk[step % 5].tolist(),
                    "reward": float(reward),
                    "success": bool(info["is_success"]),
                    "state": obs["agent_pos"].tolist(),
                }
            )
            if terminated or truncated:
                break
            if sim_viewer:
                sim_viewer.update(env._env)
        record(obs["pixels"])
        for packet in stream.encode():
            video.mux(packet)
    finally:
        if telemetry:
            telemetry.finish(success, len(history))
            telemetry.__exit__(None, None, None)
        if sim_viewer:
            sim_viewer.__exit__(None, None, None)
        video.close()
        env.close()
    result = {
        "task": task,
        "seed": seed,
        "prompt": prompt,
        "initial_state": initial_state,
        "success": success,
        "steps": len(history),
        "feedback_cycles": len(latencies),
        "inference_seconds": latencies,
        "history": history,
        "video": f"{task}-seed{seed}.mp4",
    }
    (out / f"{task}-seed{seed}.json").write_text(json.dumps(result, indent=2))
    print(
        f"task={task} seed={seed} success={success} steps={len(history)} "
        f"median_chunk={np.median(latencies):.3f}s",
        flush=True,
    )
    return {key: value for key, value in result.items() if key != "history"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--config-checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ASSETS / "pi05-metaworld-sft-nf4")
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output", type=Path, default=Path("outputs/pi05-metaworld-sft"))
    parser.add_argument("--tasks", nargs="+", default=["reach-v3", "push-v3", "pick-place-v3"])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--steps", type=int, default=160)
    parser.add_argument(
        "--visualize", action="store_true", help="Save an Rerun recording and TensorBoard metrics"
    )
    parser.add_argument("--viewer", action="store_true", help="Open a MuJoCo WSLg interactive viewer")
    parser.add_argument("--rerun-grpc", help="Optional rerun+http://HOST:PORT/proxy sink")
    args = parser.parse_args()
    if (
        not 1 <= args.steps <= 485
        or len(set(args.tasks)) != len(args.tasks)
        or len(set(args.seeds)) != len(args.seeds)
    ):
        parser.error("Use unique tasks/seeds and 1..485 policy steps")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("MUJOCO_GL", "egl")
    prompts_path = Path(__file__).with_name("metaworld_prompts.json")
    prompts = json.loads(prompts_path.read_text())
    if any(task not in prompts for task in args.tasks):
        parser.error("Unknown Meta-World task; use names from metaworld_prompts.json")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"Preserve existing evaluation: use a new output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.rerun_grpc and not args.visualize:
        parser.error("--rerun-grpc requires --visualize")
    if args.viewer:
        args.visualize = True
        os.environ["MUJOCO_GL"] = "glfw"
    stats_path = args.checkpoint / "lerobot/metaworld_mt50/norm_stats.json"
    stats = json.loads(stats_path.read_text())["norm_stats"]["actions"]
    validate_stats(stats)
    tokenizer_path = args.assets / "paligemma_tokenizer.model"
    profile = {
        "repo_id": REPO_ID,
        "stats_sha256": sha256(stats_path),
        "config_sha256": sha256(args.config_checkpoint / "config.json"),
        "tokenizer_sha256": sha256(tokenizer_path),
        "discrete_state_input": False,
        "action_indices": [0, 1, 2, 3],
        "normalization": "quantiles",
        "extra_delta_transform": False,
        "resize": "PIL bilinear uint8 224x224",
        "reference_revision": REFERENCE_REVISION,
    }
    tokenizer = spm.SentencePieceProcessor(model_file=str(tokenizer_path))
    torch.cuda.reset_peak_memory_stats()
    policy, loading = load_policy(
        args.checkpoint,
        args.artifact,
        config_checkpoint=args.config_checkpoint,
        source_revision=REVISION,
        overrides={"chunk_size": 5, "n_action_steps": 5, "num_inference_steps": 5},
        profile=profile,
    )
    save_artifact(policy, args.artifact, loading)
    report = {
        "status": "running",
        "loading": loading,
        "tasks": args.tasks,
        "seeds": args.seeds,
        "max_policy_steps": args.steps,
        "settling_steps": 15,
        "offline": True,
        "visualization": {
            "recording": args.visualize,
            "mujoco_viewer": args.viewer,
            "rerun_grpc": args.rerun_grpc,
        },
        "prompts_sha256": sha256(prompts_path),
        "camera": {"name": "corner2", "position": [0.75, 0.075, 0.7], "flip_axes": [0, 1]},
        "reset_protocol": "LeRobot MetaworldEnv MT1 seed42 train_tasks[0], unfrozen, reset(seed=episode seed)",
        "limitation": "Small local NF4 evaluation; not the full MT50 benchmark or a full-precision comparison",
        "episodes": [],
    }
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
    for task in args.tasks:
        for seed in args.seeds:
            report["episodes"].append(
                evaluate_episode(
                    policy,
                    tokenizer,
                    stats,
                    task,
                    prompts[task],
                    seed,
                    args.steps,
                    args.output,
                    visualize=args.visualize,
                    viewer=args.viewer,
                    rerun_grpc=args.rerun_grpc,
                )
            )
            report_path.write_text(json.dumps(report, indent=2))
    report.update(
        status="completed",
        successes=sum(episode["success"] for episode in report["episodes"]),
        peak_allocated_gib=torch.cuda.max_memory_allocated() / 2**30,
        peak_reserved_gib=torch.cuda.max_memory_reserved() / 2**30,
    )
    report_path.write_text(json.dumps(report, indent=2))
    print(f"Completed {report['successes']}/{len(report['episodes'])} successful episodes", flush=True)


if __name__ == "__main__":
    main()

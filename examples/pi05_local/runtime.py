"""Local PI05 NF4 inference; the Meta-World adapter is experimental, not a trained policy."""

import argparse
import gc
import hashlib
import json
import os
import time
from pathlib import Path

import av
import bitsandbytes as bnb
import numpy as np
import sentencepiece as spm
import torch
from accelerate import init_empty_weights
from safetensors import safe_open
from safetensors.torch import save_file
from torch import nn

from lerobot.policies.pi05 import PI05Config, PI05Policy
from lerobot.policies.pi05.modeling_pi05 import PI05Pytorch
from lerobot.utils.constants import OBS_LANGUAGE_ATTENTION_MASK, OBS_LANGUAGE_TOKENS

REVISION = "22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0"
DEFAULT_CHECKPOINT = Path.home() / ".cache/huggingface/hub/models--lerobot--pi05_base/snapshots" / REVISION
DEFAULT_ASSETS = Path.home() / ".local/share/lerobot-pi05"
BACKBONE = "model.paligemma_with_expert.paligemma.model.language_model.layers."


class NF4Linear(bnb.nn.Linear4bit):
    """Use BF16 activations and BF16 containers holding packed four-bit weights."""

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return super().forward(x.to(torch.bfloat16))


def normalized_state(state: np.ndarray) -> np.ndarray:
    """Experimental identity/clipped state convention, with no claimed training calibration."""
    state = np.asarray(state, dtype=np.float32)
    if state.shape != (4,) or not np.isfinite(state).all():
        raise ValueError("Meta-World state must be four finite values")
    return np.pad(np.clip(state, -1, 1), (0, 28))


def experimental_action(action: np.ndarray) -> np.ndarray:
    """Assume XYZ deltas plus index 6 gripper; base weights do not establish this meaning."""
    action = np.asarray(action, dtype=np.float32)
    if action.shape != (32,) or not np.isfinite(action).all():
        raise ValueError("PI05 action must be 32 finite values")
    return np.clip(action[[0, 1, 2, 6]], -1, 1)


def make_shell(checkpoint: Path, overrides: dict | None = None) -> PI05Policy:
    config = PI05Config.from_pretrained(checkpoint)
    for key, value in (overrides or {}).items():
        if not hasattr(config, key):
            raise ValueError(f"Unknown configuration field: {key}")
        setattr(config, key, value)
    config.device = "cpu"
    config.dtype = torch.bfloat16
    config.compile_model = False
    config.validate_features()
    # Avoid PI05Policy.__init__'s unconditional .to(device) on empty parameters.
    policy = PI05Policy.__new__(PI05Policy)
    nn.Module.__init__(policy)
    policy.config = config
    policy.init_rtc_processor()
    with init_empty_weights():
        policy.model = PI05Pytorch(config, rtc_processor=policy.rtc_processor)
    # Flow matching never calls either causal-LM output head. The PaliGemma head
    # supplies the embedding checkpoint alias below, but is not needed as a module.
    policy.model.paligemma_with_expert.paligemma.lm_head = nn.Identity()
    policy.model.paligemma_with_expert.gemma_expert.lm_head = nn.Identity()
    policy.reset()
    return policy


def validate_artifact(manifest: dict, revision: str, profile: dict) -> None:
    if manifest.get("source_revision") != revision or manifest.get("profile", {}) != profile:
        raise ValueError("Quantized artifact source/profile does not match this deployment")


def load_policy(
    checkpoint: Path,
    artifact: Path | None = None,
    *,
    config_checkpoint: Path | None = None,
    source_revision: str = REVISION,
    overrides: dict | None = None,
    profile: dict | None = None,
) -> tuple[PI05Policy, dict]:
    start = time.perf_counter()
    profile = dict(profile or {})
    if overrides:
        profile["model_overrides"] = overrides
    cached = artifact is not None and (artifact / "manifest.json").is_file()
    if cached:
        manifest = json.loads((artifact / "manifest.json").read_text())
        validate_artifact(manifest, source_revision, profile)
    policy = make_shell(config_checkpoint or checkpoint, overrides)
    params = dict(policy.named_parameters())
    quantized = [
        name
        for name, module in policy.named_modules()
        if name.startswith(BACKBONE) and isinstance(module, nn.Linear)
    ]
    for name in quantized:
        old = policy.get_submodule(name)
        with torch.device("meta"):
            new = NF4Linear(
                old.in_features,
                old.out_features,
                bias=old.bias is not None,
                compute_dtype=torch.bfloat16,
                compress_statistics=True,
                quant_type="nf4",
                quant_storage=torch.bfloat16,
            )
        policy.set_submodule(name, new)
    if cached and manifest["quantized_modules"] != quantized:
        raise ValueError("Quantized artifact does not match this deployment")
    source = artifact / "model.safetensors" if cached else checkpoint / "model.safetensors"
    used = set()
    with safe_open(source, framework="pt", device="cpu") as weights:
        keys = set(weights.keys())
        for index, (name, template) in enumerate(params.items()):
            source_key = name if cached else name.removeprefix("model.")
            if not cached and source_key.endswith("paligemma.model.language_model.embed_tokens.weight"):
                source_key = "paligemma_with_expert.paligemma.lm_head.weight"
            if source_key not in keys:
                raise ValueError(f"Missing pretrained weight: {source_key}")
            value = weights.get_tensor(source_key)
            used.add(source_key)
            parent_name, field = name.rsplit(".", 1)
            parent = policy.get_submodule(parent_name)
            if isinstance(parent, NF4Linear) and field == "weight":
                if cached:
                    stats = {key: weights.get_tensor(key) for key in keys if key.startswith(name + ".")}
                    used.update(stats)
                    value = bnb.nn.Params4bit.from_prequantized(value, stats, device="cuda", module=parent)
                    parent.quant_state = value.quant_state
                else:
                    if value.shape != template.shape:
                        raise ValueError(f"Shape mismatch: {name}")
                    value = bnb.nn.Params4bit(
                        value.to(torch.bfloat16),
                        requires_grad=False,
                        quant_type="nf4",
                        compress_statistics=True,
                        module=parent,
                        quant_storage=torch.bfloat16,
                    ).to("cuda")
                parent.weight = value
            else:
                if value.shape != template.shape:
                    raise ValueError(f"Shape mismatch: {name}")
                setattr(parent, field, nn.Parameter(value.to(device="cuda", dtype=template.dtype), False))
            if index % 100 == 0:
                print(f"Loaded {index + 1}/{len(params)} tensors", flush=True)
        unused_heads = set() if cached else {"paligemma_with_expert.gemma_expert.lm_head.weight"}
        if keys - used - unused_heads:
            raise ValueError(f"Unconsumed checkpoint keys: {sorted(keys - used - unused_heads)[:8]}")
    for name, buffer in list(policy.named_buffers()):
        if buffer.is_meta:
            raise ValueError(f"Uninitialized buffer: {name}")
        parent_name, field = name.rsplit(".", 1)
        setattr(policy.get_submodule(parent_name), field, buffer.to("cuda"))
    if any(p.is_meta for p in policy.parameters()):
        raise ValueError("Uninitialized parameter")
    policy.config.device = "cuda"
    policy.requires_grad_(False).eval()
    gc.collect()
    torch.cuda.empty_cache()
    report = {
        "source_revision": source_revision,
        "profile": profile,
        "quantized_modules": quantized,
        "quantization": "NF4 double quantization, language decoder linear layers only",
        "compute_dtype": "bfloat16",
        "loaded_tensors": len(params),
        "load_seconds": time.perf_counter() - start,
        "allocated_gib": torch.cuda.memory_allocated() / 2**30,
        "bnb_version": bnb.__version__,
        "torch_version": torch.__version__,
    }
    return policy, report


def save_artifact(policy: PI05Policy, folder: Path, report: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "manifest.json").exists():
        return
    state = {key: value.detach().cpu().contiguous() for key, value in policy.state_dict().items()}
    temporary = folder / "model.safetensors.partial"
    save_file(state, str(temporary))
    temporary.replace(folder / "model.safetensors")
    report = dict(report, artifact_bytes=(folder / "model.safetensors").stat().st_size)
    (folder / "manifest.json").write_text(json.dumps(report, indent=2))
    del state
    gc.collect()


def prepare_batch(
    image: np.ndarray, state: np.ndarray, task: str, tokenizer: spm.SentencePieceProcessor
) -> dict:
    if image.ndim != 3 or image.shape[-1] != 3 or image.dtype != np.uint8:
        raise ValueError("Expected HWC uint8 RGB image")
    state = normalized_state(state)
    bins = np.digitize(state, np.linspace(-1, 1, 257)[:-1]) - 1
    cleaned = task.strip().replace("_", " ").replace("\n", " ")
    prompt = f"Task: {cleaned}, State: {' '.join(map(str, bins))};\nAction: "
    tokens = tokenizer.encode(prompt, add_bos=True)
    if len(tokens) > 200:
        raise ValueError("Prompt exceeds 200 tokens")
    mask = [True] * len(tokens) + [False] * (200 - len(tokens))
    tokens += [0] * (200 - len(tokens))
    return {
        "observation.images.base_0_rgb": torch.from_numpy(image.copy())
        .permute(2, 0, 1)[None]
        .to("cuda")
        .float()
        / 255,
        "observation.state": torch.from_numpy(state)[None].to("cuda"),
        OBS_LANGUAGE_TOKENS: torch.tensor([tokens], device="cuda"),
        OBS_LANGUAGE_ATTENTION_MASK: torch.tensor([mask], device="cuda"),
    }


def rollout(args: argparse.Namespace) -> None:
    # Set before importing MuJoCo/OpenGL.
    os.environ.setdefault("MUJOCO_GL", "egl")
    from lerobot.envs.metaworld import MetaworldEnv

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    tokenizer_path = Path(args.assets) / "paligemma_tokenizer.model"
    tokenizer = spm.SentencePieceProcessor(model_file=str(tokenizer_path))
    torch.manual_seed(args.seed)
    torch.cuda.reset_peak_memory_stats()
    policy, loading = load_policy(Path(args.checkpoint), Path(args.artifact))
    if args.export:
        save_artifact(policy, Path(args.artifact), loading)
    env = MetaworldEnv(args.task, obs_type="pixels_agent_pos")
    latencies, history = [], []
    success = False
    video = av.open(str(out / "rollout.mp4"), "w")
    stream = video.add_stream("libx264", rate=20)
    stream.width, stream.height, stream.pix_fmt = 480, 480, "yuv420p"
    try:
        obs, _ = env.reset(seed=args.seed)
        for step in range(args.steps):
            if step % args.horizon == 0:
                batch = prepare_batch(obs["pixels"], obs["agent_pos"], env.task_description, tokenizer)
                torch.cuda.synchronize()
                start = time.perf_counter()
                with torch.inference_mode():
                    chunk = policy.predict_action_chunk(batch).float().cpu().numpy()[0]
                torch.cuda.synchronize()
                latencies.append(time.perf_counter() - start)
                if not np.isfinite(chunk).all():
                    raise ValueError("Non-finite model output")
                print(
                    f"step={step} inference={latencies[-1]:.3f}s allocated={torch.cuda.memory_allocated() / 2**30:.2f}GiB",
                    flush=True,
                )
            frame = av.VideoFrame.from_ndarray(obs["pixels"], format="rgb24")
            for packet in stream.encode(frame):
                video.mux(packet)
            action = experimental_action(chunk[step % args.horizon])
            obs, reward, terminated, truncated, info = env.step(action)
            history.append({"step": step, "action": action.tolist(), "reward": float(reward)})
            success = success or bool(info["is_success"])
            if terminated or truncated:
                break
        for packet in stream.encode():
            video.mux(packet)
    finally:
        video.close()
        env.close()
    report = {
        "status": "completed",
        "task": args.task,
        "seed": args.seed,
        "steps": len(history),
        "feedback_cycles": len(latencies),
        "success": success,
        "inference_seconds": latencies,
        "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
        "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
        "loading": loading,
        "tokenizer_sha256": hashlib.sha256(tokenizer_path.read_bytes()).hexdigest(),
        "limitation": "Uncalibrated base-model Meta-World adapter; no trained action semantics or task success guarantee",
        "history": history,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in ("history", "loading")}, indent=2
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--assets", default=str(DEFAULT_ASSETS))
    parser.add_argument("--artifact", default=str(DEFAULT_ASSETS / "pi05-nf4"))
    parser.add_argument("--output", default="outputs/pi05-local")
    parser.add_argument("--task", default="reach-v3")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    if args.steps < 1 or not 1 <= args.horizon <= 50:
        parser.error("steps must be positive and horizon must be in [1, 50]")
    rollout(args)


if __name__ == "__main__":
    main()

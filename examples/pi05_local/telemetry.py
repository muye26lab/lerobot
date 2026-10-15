"""Optional local visualization for PI05; all recorded trajectories are observations."""

import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import torch


@contextmanager
def capture_denoising(model: Any) -> Iterator[list[tuple[torch.Tensor, torch.Tensor]]]:
    """Capture flow inputs on device, without changing outputs or synchronizing each step."""
    original = model.denoise_step
    had_override = "denoise_step" in model.__dict__
    trace = []

    def traced(*args: Any, **kwargs: Any) -> torch.Tensor:
        trace.append((kwargs["timestep"].detach().clone(), kwargs["x_t"][0].detach().clone()))
        return original(*args, **kwargs)

    model.denoise_step = traced
    try:
        yield trace
    finally:
        if had_override:
            model.denoise_step = original
        else:
            del model.denoise_step


class EpisodeTelemetry:
    """One independently replayable episode, with aligned post-action observations."""

    def __init__(self, out: Path, task: str, seed: int, prompt: str, grpc_url: str | None = None):
        import rerun as rr
        import rerun.blueprint as rrb
        from torch.utils.tensorboard import SummaryWriter

        self.rr = rr
        self.name = f"{task}-seed{seed}"
        self.out = out
        self.recording = rr.RecordingStream("pi05-metaworld", recording_id=self.name + "-" + out.name)
        sinks = [rr.FileSink(str(out / f"{self.name}.rrd"))]
        if grpc_url:
            sinks.append(rr.GrpcSink(grpc_url))
        self.recording.set_sinks(*sinks)
        self.writer = SummaryWriter(str(out / "tensorboard" / self.name), flush_secs=2)
        self.positions: list[list[float]] = []
        self.traces: dict[str, np.ndarray] = {}
        self.recording.send_blueprint(
            rrb.Blueprint(
                rrb.Vertical(
                    rrb.Horizontal(
                        rrb.Spatial2DView(origin="camera", name="Robot camera"),
                        rrb.Spatial3DView(origin="world", name="Measured end-effector path (metres)"),
                        rrb.TextDocumentView(origin="info", name="Task and timing"),
                        column_shares=[3, 3, 2],
                    ),
                    rrb.Horizontal(
                        rrb.TimeSeriesView(origin="action", name="Executed action [-1,1]"),
                        rrb.TimeSeriesView(origin="state", name="Observed XYZ / gripper"),
                        rrb.TimeSeriesView(origin="metrics", name="Reward / success / inference seconds"),
                    ),
                    rrb.Horizontal(
                        rrb.TensorView(origin="prediction/chunk", name="Final normalized actions [5,4]"),
                        rrb.TensorView(
                            origin="prediction/flow", name="Flow states [6,5,4]; not robot positions"
                        ),
                    ),
                    row_shares=[4, 2, 2],
                ),
                collapse_panels=True,
            )
        )
        self.recording.log(
            "info",
            rr.TextDocument(
                f"# {task} / seed {seed}\n{prompt}\n\n"
                "step 0: settled observation. step N: observation after action N.\n\n"
                "Action/reward at N belong to transition N-1 -> N. "
                "Predictions at N use observation N.\n\n"
                "Flow tensor axes: denoise stage, future action index, XYZ/gripper. "
                "Stages 0..4 are noisy inputs, stage 5 is the final normalized output. "
                "These are not spatial coordinates. No training is running.",
                media_type="text/markdown",
            ),
            static=True,
        )
        self.recording.log("world", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)

    def observe(self, step: int, image: np.ndarray, state: np.ndarray) -> None:
        self.recording.set_time("step", sequence=step)
        self.recording.log("camera", self.rr.Image(image).compress(jpeg_quality=85))
        for name, value in zip(("x", "y", "z", "gripper"), state, strict=True):
            self.recording.log(f"state/{name}", self.rr.Scalars(float(value)))
        self.positions.append(state[:3].tolist())
        self.recording.log(
            "world/end_effector", self.rr.Points3D([state[:3]], radii=0.008, colors=[40, 180, 255])
        )
        if len(self.positions) > 1:
            self.recording.log("world/path", self.rr.LineStrips3D([self.positions], radii=0.002))

    def transition(
        self,
        step: int,
        image: np.ndarray,
        state: np.ndarray,
        action: np.ndarray,
        reward: float,
        success: bool,
    ) -> None:
        self.observe(step, image, state)
        for name, value in zip(("x", "y", "z", "gripper"), action, strict=True):
            self.recording.log(f"action/{name}", self.rr.Scalars(float(value)))
        for name, value in (("reward", reward), ("success", float(success))):
            self.recording.log(f"metrics/{name}", self.rr.Scalars(value))
            self.writer.add_scalar(f"eval/{name}", value, step)

    def inference(
        self, step: int, chunk: np.ndarray, trace: list[tuple[Any, torch.Tensor]], elapsed: float
    ) -> None:
        states = [value.float().cpu().numpy() for _, value in trace] + [chunk]
        times = [float(time) for time, _ in trace] + [0.0]
        self.traces[f"chunk_{step}_states"] = np.stack(states)
        self.traces[f"chunk_{step}_times"] = np.asarray(times)
        self.recording.set_time("step", sequence=step)
        self.recording.log(
            "prediction/chunk", self.rr.Tensor(chunk[:, :4], dim_names=["future action", "XYZ/gripper"])
        )
        self.recording.log(
            "prediction/flow",
            self.rr.Tensor(np.stack(states)[:, :, :4], dim_names=["stage", "future action", "XYZ/gripper"]),
        )
        self.recording.log("metrics/inference_seconds", self.rr.Scalars(elapsed))
        self.writer.add_scalar("inference/chunk_seconds", elapsed, step)

    def finish(self, success: bool, steps: int) -> None:
        self.writer.add_scalar("episode/success", float(success), steps)
        self.writer.add_scalar("episode/steps", steps, steps)

    def __enter__(self) -> "EpisodeTelemetry":
        return self

    def __exit__(self, *_: Any) -> None:
        if self.traces:
            np.savez_compressed(self.out / f"{self.name}-denoising.npz", **self.traces)
        self.writer.close()
        self.recording.flush()
        self.recording.disconnect()


class SimulationViewer:
    """Passive viewer of a copied world; mouse interactions cannot alter the policy world."""

    def __init__(self, env: Any):
        import mujoco
        import mujoco.viewer

        self.mujoco = mujoco
        self.model = copy.copy(env.model)
        self.data = mujoco.MjData(self.model)
        mujoco.mj_copyData(self.data, self.model, env.data)
        previous_threads = set(threading.enumerate())
        self.handle = mujoco.viewer.launch_passive(self.model, self.data)
        # MuJoCo 3.8 launches a daemon renderer and close() only requests exit.
        # Join that renderer before the environment tears down its GLFW context.
        self.render_threads = [
            thread
            for thread in threading.enumerate()
            if thread not in previous_threads and "_launch_internal" in thread.name
        ]
        self.handle.cam.lookat[:] = [0, 0.65, 0.15]
        self.handle.cam.distance = 1.5
        self.handle.cam.azimuth = 135
        self.handle.cam.elevation = -25

    def update(self, env: Any) -> None:
        if self.handle.is_running():
            with self.handle.lock():
                self.mujoco.mj_copyData(self.data, self.model, env.data)
            self.handle.sync()

    def __enter__(self) -> "SimulationViewer":
        return self

    def __exit__(self, *_: Any) -> None:
        self.handle.close()
        for thread in self.render_threads:
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("MuJoCo renderer did not shut down within 10 seconds")

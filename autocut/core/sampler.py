"""Sampled frame decoding through an ffmpeg pipe (ADR 2).

One ffmpeg process per file writes raw RGB frames at the configured sample rate
and long side to stdout, and the Python side reads fixed size frames straight
into NumPy. Full 4K decoding never happens: the ``fps`` and ``scale`` filters run
inside ffmpeg, so only the sampled, downscaled frames cross the pipe.

The output size is computed here rather than left to ffmpeg's ``-2`` rounding,
because the reader needs to know the exact frame size before the first byte
arrives. ffmpeg autorotation is on by default, so the filter chain sees display
dimensions and the frames come out upright.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from autocut.core.config import AutocutConfig
from autocut.core.hwaccel import SOFTWARE, Hwaccel
from autocut.core.probe import ProbeResult

FrameSource = Literal["proxy", "original"]

# ffmpeg exits 0 but writes nothing for a file it cannot decode; guard the read anyway.
READ_TIMEOUT_S = 900.0


@dataclass(slots=True)
class SampledFrames:
    """The frames of one file, plus where they came from."""

    timestamps: np.ndarray
    frames: np.ndarray
    source: FrameSource
    path: Path
    hwaccel_used: str = "none"
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return int(self.frames.shape[0])


def sample_size(probe: ProbeResult, long_side: int) -> tuple[int, int]:
    """Even width and height that fit ``long_side`` on the longer display edge."""
    width, height = probe.display_width, probe.display_height
    if width <= 0 or height <= 0:
        return 0, 0
    if width >= height:
        out_w = long_side
        out_h = max(2, _even(round(height * long_side / width)))
    else:
        out_h = long_side
        out_w = max(2, _even(round(width * long_side / height)))
    return out_w, out_h


def _even(value: int) -> int:
    return value - (value % 2)


def build_sample_command(
    path: Path,
    fps: float,
    width: int,
    height: int,
    hwaccel: Hwaccel = SOFTWARE,
) -> list[str]:
    """ffmpeg arguments that write sampled ``rgb24`` frames of ``width`` x ``height``."""
    # The decoder flags must precede -i: they select the decoder for the input
    # that follows. The method itself was decided once for the whole run.
    command = ["ffmpeg", "-v", "error", "-nostdin", *hwaccel.input_flags()]
    command += [
        "-i",
        str(path),
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={fps:g},scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    return command


def build_single_frame_command(path: Path, width: int, height: int) -> list[str]:
    """Grab exactly one frame, for clips too short for the ``fps`` filter to emit any.

    The Action 4 leaves aborted recordings of a single frame behind. At two frames
    per second ffmpeg's ``fps`` filter needs at least half a sample period of
    material and returns nothing, which would leave the file with no segment at all
    instead of one that the length rule can reject.
    """
    return [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]


def read_frames(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
    """Run ``command`` and read whole frames from its stdout. Returns frames, code, stderr."""
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL
        )
    except FileNotFoundError:
        return [], 127, "ffmpeg not found on PATH"
    frames: list[bytes] = []
    assert process.stdout is not None
    try:
        while True:
            chunk = process.stdout.read(frame_bytes)
            if not chunk or len(chunk) < frame_bytes:
                break
            frames.append(chunk)
        process.stdout.close()
        _, stderr = process.communicate(timeout=READ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return frames, 1, "ffmpeg timed out"
    return frames, process.returncode, stderr.decode("utf-8", errors="replace")


def sample_frames(
    path: Path,
    probe: ProbeResult,
    config: AutocutConfig,
    proxy: Path | None = None,
    hwaccel: Hwaccel = SOFTWARE,
) -> SampledFrames:
    """Sample ``path``, or its proxy when one is attached and proxies are enabled."""
    use_proxy = proxy is not None and config.analysis.use_proxies
    target = proxy if use_proxy and proxy is not None else path
    source: FrameSource = "proxy" if use_proxy else "original"

    width, height = sample_size(probe, config.analysis.sample_long_side)
    if width == 0 or height == 0:
        return SampledFrames(
            timestamps=np.zeros(0),
            frames=np.zeros((0, 0, 0, 3), dtype=np.uint8),
            source=source,
            path=target,
            warnings=["unknown frame size, nothing sampled"],
        )

    frame_bytes = width * height * 3
    warnings: list[str] = []
    # The run already chose and verified its decoder, so the hardware attempt is
    # expected to work. The software retry stays as a per-file last resort for a
    # single unreadable clip, not as the systematic second spawn it used to be.
    attempts: list[Hwaccel] = [hwaccel] if not hwaccel.enabled else [hwaccel, SOFTWARE]

    raw: list[bytes] = []
    hwaccel_used = "none"
    for index, attempt in enumerate(attempts):
        command = build_sample_command(target, config.analysis.sample_fps, width, height, attempt)
        raw, returncode, stderr = read_frames(command, frame_bytes)
        if returncode == 0 and raw:
            hwaccel_used = attempt.method
            break
        if index + 1 < len(attempts):
            warnings.append(
                f"{attempt.label()} decoding failed on this file, "
                f"retrying in software: {stderr.strip()}"
            )
            raw = []

    if not raw:
        raw, returncode, stderr = read_frames(
            build_single_frame_command(target, width, height), frame_bytes
        )
        if raw:
            warnings.append("clip too short to sample, took a single frame")
        else:
            warnings.append(f"no frames decoded: {stderr.strip()}")
            return SampledFrames(
                timestamps=np.zeros(0),
                frames=np.zeros((0, height, width, 3), dtype=np.uint8),
                source=source,
                path=target,
                warnings=warnings,
            )

    frames = np.frombuffer(b"".join(raw), dtype=np.uint8).reshape(len(raw), height, width, 3)
    timestamps = np.arange(len(raw), dtype=np.float64) / config.analysis.sample_fps
    return SampledFrames(
        timestamps=timestamps,
        frames=frames,
        source=source,
        path=target,
        hwaccel_used=hwaccel_used,
        warnings=warnings,
    )

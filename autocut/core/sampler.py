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
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Literal

import numpy as np

from autocut.core.config import AutocutConfig
from autocut.core.hwaccel import SOFTWARE, Hwaccel
from autocut.core.probe import ProbeResult

FrameSource = Literal["proxy", "original"]

# ffmpeg exits 0 but writes nothing for a file it cannot decode; guard the read anyway.
READ_TIMEOUT_S = 900.0

# Keep only the tail of stderr for the error message; a noisy decoder can write
# far more than anyone would want to read.
STDERR_TAIL_BYTES = 65536


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


def _drain_stderr(pipe: IO[bytes], tail: bytearray, lock: threading.Lock) -> None:
    """Read ``pipe`` to EOF, keeping only the last ``STDERR_TAIL_BYTES`` bytes of it."""
    while True:
        chunk = pipe.read(4096)
        if not chunk:
            break
        with lock:
            tail.extend(chunk)
            if len(tail) > STDERR_TAIL_BYTES:
                del tail[: len(tail) - STDERR_TAIL_BYTES]


def _readinto_full(stream: IO[bytes], view: memoryview, size: int) -> int:
    """Read exactly ``size`` bytes into ``view``, looping over short reads.

    A pipe's ``readinto`` can return fewer bytes than asked for even mid-stream.
    Only an EOF (a read of zero bytes) ends the loop before ``size`` is reached,
    which is what lets a genuinely partial final frame still be detected as
    partial (design decision 3, issue #82, and its short-read risk).
    """
    filled = 0
    while filled < size:
        # subprocess.Popen types stdout as IO[bytes], which has no readinto, but a
        # pipe's stdout is a BufferedReader at runtime and always has one.
        read = stream.readinto(view[filled:size])  # type: ignore[attr-defined]
        if not read:
            break
        filled += read
    return filled


def _finish(buffer: np.ndarray, count: int) -> np.ndarray:
    """The frames actually read: a copy when the buffer overshot by a lot, else a view.

    Copying only below half capacity keeps a well guessed ``expected`` free of a
    copy, and still frees the wasted tail of a buffer that grew, or was sized,
    much larger than what came back.
    """
    view = buffer[:count]
    return view.copy() if count < buffer.shape[0] // 2 else view


def read_frames(
    command: list[str], shape: tuple[int, int, int], expected: int
) -> tuple[np.ndarray, int, str]:
    """Run ``command`` and decode whole frames straight into one growing array.

    ``shape`` is one frame's ``(height, width, channels)``. The buffer starts at
    ``expected`` frames and doubles, copy and drop the old one, whenever a frame
    would not fit; the array returned is at most one copy of the sampled frames,
    not the two a list-of-bytes-then-stack would cost (design decision 3, issue
    #82). Returns the frames, the process exit code and stderr.

    ffmpeg's stderr is drained on a background thread while stdout is read, so a
    decoder that writes a lot of error output before or between frames cannot fill
    the stderr pipe and deadlock the stdout read (decision 1, issue #78).
    """
    height, width, channels = shape
    frame_bytes = height * width * channels
    capacity = max(expected, 1)
    buffer = np.empty((capacity, height, width, channels), dtype=np.uint8)

    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL
        )
    except FileNotFoundError:
        return buffer[:0], 127, "ffmpeg not found on PATH"
    assert process.stdout is not None
    assert process.stderr is not None

    stderr_tail = bytearray()
    stderr_lock = threading.Lock()
    stderr_thread = threading.Thread(
        target=_drain_stderr, args=(process.stderr, stderr_tail, stderr_lock), daemon=True
    )
    stderr_thread.start()

    count = 0
    try:
        while True:
            if count >= buffer.shape[0]:
                grown = np.empty((buffer.shape[0] * 2, height, width, channels), dtype=np.uint8)
                grown[:count] = buffer[:count]
                buffer = grown
            view = memoryview(buffer[count]).cast("B")
            read = _readinto_full(process.stdout, view, frame_bytes)
            if read < frame_bytes:
                break
            count += 1
        process.stdout.close()
        process.wait(timeout=READ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        stderr_thread.join(timeout=5.0)
        with stderr_lock:
            tail = bytes(stderr_tail)
        return _finish(buffer, count), 1, "ffmpeg timed out"
    stderr_thread.join(timeout=5.0)
    with stderr_lock:
        tail = bytes(stderr_tail)
    return _finish(buffer, count), process.returncode, tail.decode("utf-8", errors="replace")


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

    shape = (height, width, 3)
    # A little over the frame count a whole file at this sample rate would give,
    # so an ordinary file needs no growth; a short read still grows the buffer.
    expected = int(probe.duration_s * config.analysis.sample_fps) + 2
    warnings: list[str] = []
    # The run already chose and verified its decoder, so the hardware attempt is
    # expected to work. The software retry stays as a per-file last resort for a
    # single unreadable clip, not as the systematic second spawn it used to be.
    attempts: list[Hwaccel] = [hwaccel] if not hwaccel.enabled else [hwaccel, SOFTWARE]

    raw = np.zeros((0, height, width, 3), dtype=np.uint8)
    hwaccel_used = "none"
    for index, attempt in enumerate(attempts):
        command = build_sample_command(target, config.analysis.sample_fps, width, height, attempt)
        raw, returncode, stderr = read_frames(command, shape, expected)
        if returncode == 0 and raw.shape[0] > 0:
            hwaccel_used = attempt.method
            break
        if index + 1 < len(attempts):
            warnings.append(
                f"{attempt.label()} decoding failed on this file, "
                f"retrying in software: {stderr.strip()}"
            )
            raw = np.zeros((0, height, width, 3), dtype=np.uint8)

    if raw.shape[0] == 0:
        raw, returncode, stderr = read_frames(
            build_single_frame_command(target, width, height), shape, expected=1
        )
        if raw.shape[0] > 0:
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

    timestamps = np.arange(raw.shape[0], dtype=np.float64) / config.analysis.sample_fps
    return SampledFrames(
        timestamps=timestamps,
        frames=raw,
        source=source,
        path=target,
        hwaccel_used=hwaccel_used,
        warnings=warnings,
    )

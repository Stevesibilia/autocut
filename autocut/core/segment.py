"""Shot detection and per-class head and tail trimming.

Detection runs on the frames already sampled for metrics rather than decoding the
file a second time. PySceneDetect stays available behind
``analysis.detector = "pyscenedetect"`` for validation, but it decodes the video
itself and would double the cost of every run, so the in-memory detector is the
default. Boundary precision is therefore the sample period, which is fine for
candidates that a later stage windows anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from autocut.core.config import AutocutConfig, SourceClass

Bounds = tuple[float, float]

ALTITUDE_SPLIT = "altitude"


@dataclass(frozen=True, slots=True)
class Span:
    """A candidate span and, when it is not a whole shot, why it was cut out of one."""

    start_s: float
    end_s: float
    split_reason: str | None = None

    @property
    def bounds(self) -> Bounds:
        return self.start_s, self.end_s


def content_series(frames: np.ndarray) -> np.ndarray:
    """Per-frame content difference to the previous frame, 0 to 1.

    HSV mean absolute difference, the signal PySceneDetect's ``ContentDetector``
    thresholds. The first frame has no predecessor and scores 0.
    """
    count = int(frames.shape[0])
    if count < 2:
        return np.zeros(max(count, 0))
    hsv = np.stack([cv2.cvtColor(frame, cv2.COLOR_RGB2HSV) for frame in frames]).astype(np.float64)
    diffs = np.abs(np.diff(hsv, axis=0)).mean(axis=(1, 2, 3)) / 255.0
    return np.concatenate(([0.0], diffs))


def detect_shots(
    frames: np.ndarray,
    timestamps: np.ndarray,
    threshold: float,
    min_len: float,
    duration_s: float | None = None,
) -> list[Bounds]:
    """Split the sampled frames into shot bounds. One continuous shot yields one span."""
    count = int(frames.shape[0])
    end = float(duration_s) if duration_s else (float(timestamps[-1]) if count else 0.0)
    if count == 0 or end <= 0:
        return [(0.0, max(end, 0.0))] if end > 0 else []

    scores = content_series(frames)
    cuts: list[float] = []
    last_cut = 0.0
    for index in range(1, count):
        moment = float(timestamps[index])
        if scores[index] < threshold:
            continue
        if moment - last_cut < min_len or end - moment < min_len:
            continue
        cuts.append(moment)
        last_cut = moment

    edges = [0.0, *cuts, end]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def detect_shots_pyscenedetect(path: Path, threshold: float, min_len_frames: int) -> list[Bounds]:
    """Shot bounds from PySceneDetect, decoding the file itself. Validation path only."""
    from scenedetect import ContentDetector, detect  # noqa: PLC0415

    scenes = detect(
        str(path),
        ContentDetector(threshold=threshold * 255.0, min_scene_len=min_len_frames),
    )
    return [(start.get_seconds(), stop.get_seconds()) for start, stop in scenes]


def split_on_altitude(
    bounds: list[Bounds],
    heights: list[tuple[float, float]],
    threshold: float,
    grid_s: float,
) -> list[Span]:
    """Cut each span where the aircraft crosses ``threshold``.

    A takeoff is not a separate shot: the camera runs continuously from the ground
    into the cruise, so shot detection sees one span and the low altitude rule,
    which looks at the maximum height over a segment, can never fire on it.
    Rejecting the whole shot on its minimum height instead would throw away the
    cruise footage, which is the material worth keeping.

    So the crossings themselves become boundaries. The parts that stay below the
    threshold become their own spans and get rejected by the ordinary rule; the
    parts above are left alone. This applies at both ends and in the middle, so a
    flight that dips low over a beach and climbs again yields three spans.

    Boundaries land on telemetry sample times, snapped to the frame sampling grid
    so that segment bounds stay on the grid metrics were measured on.
    """
    if not heights or threshold <= 0:
        return [Span(start, stop) for start, stop in bounds]

    ordered = sorted(heights)
    spans: list[Span] = []
    for start, stop in bounds:
        inside = [(time_s, height) for time_s, height in ordered if start <= time_s < stop]
        cuts = _altitude_cuts(inside, threshold, grid_s, start, stop)
        if not cuts:
            spans.append(Span(start, stop))
            continue
        edges = [start, *cuts, stop]
        spans.extend(
            Span(edges[index], edges[index + 1], ALTITUDE_SPLIT) for index in range(len(edges) - 1)
        )
    return spans


def _altitude_cuts(
    samples: list[tuple[float, float]],
    threshold: float,
    grid_s: float,
    start: float,
    stop: float,
) -> list[float]:
    """Times where the below/above state flips, snapped to the sampling grid."""
    cuts: list[float] = []
    previous: bool | None = None
    for time_s, height in samples:
        below = height < threshold
        if previous is not None and below != previous:
            moment = _snap(time_s, grid_s)
            if start < moment < stop and (not cuts or moment > cuts[-1]):
                cuts.append(moment)
        previous = below
    return cuts


def _snap(value: float, grid_s: float) -> float:
    if grid_s <= 0:
        return value
    return round(round(value / grid_s) * grid_s, 6)


def apply_trims(
    bounds: list[Bounds],
    duration_s: float,
    source_class: SourceClass,
    config: AutocutConfig,
) -> list[Bounds | None]:
    """Clamp each span to the usable middle of the file, per class.

    Returns one entry per input span, ``None`` where the trim swallowed the span
    entirely, so callers keep the mapping to their detected shots.
    """
    head = config.analysis.head_trim_seconds.get(source_class)
    tail = config.analysis.tail_trim_seconds.get(source_class)
    low = min(head, duration_s)
    high = max(low, duration_s - tail)
    trimmed: list[Bounds | None] = []
    for start, stop in bounds:
        new_start = max(start, low)
        new_stop = min(stop, high)
        trimmed.append((new_start, new_stop) if new_stop > new_start else None)
    return trimmed

"""Best window search inside a candidate segment (ADR 5).

Selection stores where the good part of a segment is, not where the clip will be
cut. Beat sync only learns the real BPM after the user has generated the track,
so the final duration is decided then; storing a center and a target keeps that
choice open and costs nothing.

The search runs on the per-frame arrays already in the cache, so it never decodes
video. Frames are scored with the same per-class rank normalization the segment
score uses, but pooled over every frame of the class rather than over segment
means: reusing one segment score for all its frames would make every window equal
and there would be nothing to search.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from autocut.core.config import ScoringWeights
from autocut.core.score import SCORED_METRICS

# Cache array names, in the order the scoring table refers to them.
METRIC_ARRAYS = {
    "sharpness": "sharpness",
    "exposure_clipped": "clipping",
    "motion": "motion",
    "stability": "stability",
    "colorfulness": "colorfulness",
}


@dataclass(slots=True)
class ClassNorms:
    """Sorted per-frame values of one source class, used to rank any frame against it."""

    sorted_values: dict[str, np.ndarray] = field(default_factory=dict)

    def normalize(self, metric: str, values: np.ndarray) -> np.ndarray:
        """Rank ``values`` against every frame of the class, mapped to 0 to 1."""
        reference = self.sorted_values.get(metric)
        if reference is None or reference.size < 2 or values.size == 0:
            return np.full(values.shape, 0.5)
        ranks = np.searchsorted(reference, values, side="left").astype(np.float64)
        return np.clip(ranks / (reference.size - 1), 0.0, 1.0)


def build_class_norms(
    frames_by_class: dict[str, list[dict[str, np.ndarray]]],
) -> dict[str, ClassNorms]:
    """Pool every frame of each class so a frame can be ranked against its own class."""
    norms: dict[str, ClassNorms] = {}
    for source_class, arrays_list in frames_by_class.items():
        pooled: dict[str, np.ndarray] = {}
        for metric, array_name in METRIC_ARRAYS.items():
            values = [arrays[array_name] for arrays in arrays_list if array_name in arrays]
            if values:
                pooled[metric] = np.sort(np.concatenate(values))
        norms[source_class] = ClassNorms(sorted_values=pooled)
    return norms


def frame_scores(
    arrays: dict[str, np.ndarray], class_norms: ClassNorms, weights: ScoringWeights
) -> np.ndarray:
    """One composite score per sampled frame, weighted exactly like the segment score."""
    timestamps = arrays.get("timestamps")
    if timestamps is None or timestamps.size == 0:
        return np.zeros(0)

    total_weight = 0.0
    accumulated = np.zeros(timestamps.shape[0], dtype=np.float64)
    for metric, weight_name, lower_is_better in SCORED_METRICS:
        weight = float(getattr(weights, weight_name))
        if weight <= 0:
            continue
        values = arrays.get(METRIC_ARRAYS[metric])
        if values is None or values.size != timestamps.size:
            continue
        normalized = class_norms.normalize(metric, values)
        if lower_is_better:
            normalized = 1.0 - normalized
        accumulated += weight * normalized
        total_weight += weight

    if total_weight <= 0:
        return np.full(timestamps.shape[0], 0.5)
    return accumulated / total_weight


def best_window(
    scores: np.ndarray,
    timestamps: np.ndarray,
    trimmed_bounds: tuple[float, float],
    target_s: float,
) -> tuple[float, float]:
    """Center and duration of the highest scoring window inside ``trimmed_bounds``.

    A segment shorter than the target keeps its whole trimmed span. The window
    never leaves the trimmed bounds: the last position considered is the one whose
    end sits exactly on the trimmed end, so a segment whose best frames are its
    last frames gets a window flush with that end.
    """
    start, stop = trimmed_bounds
    span = max(stop - start, 0.0)
    if span <= 0:
        return start, 0.0
    if span <= target_s:
        return (start + stop) / 2.0, span

    inside = np.flatnonzero((timestamps >= start) & (timestamps < stop))
    if inside.size == 0 or scores.size != timestamps.size:
        return (start + stop) / 2.0, target_s

    # Every frame start that fits, plus the flush-right position, which the frame
    # grid does not necessarily land on.
    starts = [float(timestamps[index]) for index in inside if timestamps[index] + target_s <= stop]
    starts.append(stop - target_s)

    best_start = starts[0]
    best_mean = -np.inf
    for candidate_start in starts:
        window = np.flatnonzero(
            (timestamps >= candidate_start) & (timestamps < candidate_start + target_s)
        )
        if window.size == 0:
            continue
        mean = float(scores[window].mean())
        if mean > best_mean:
            best_mean = mean
            best_start = candidate_start

    return best_start + target_s / 2.0, target_s

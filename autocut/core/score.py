"""Composite scoring across the segments of one run.

Every metric is rank normalized before being weighted, so one outlier cannot
dominate and the diversity and weight sliders in the GUI behave predictably.

Normalization runs per source class, not across the whole project. Raw metrics
are not comparable between classes: on the Sardinia set the action cam segments
are sampled from 720p proxies and the drone segments from 4K originals, which
gave the action cams a median sharpness of 1343 against 996 and ten of the top
twelve places, for reasons that have nothing to do with which clip is better.
Ranking within a class removes that; keeping the classes in proportion is the
job of the per-class quota in selection, not of the score.

The consequence is that a score is comparable within one class of one manifest
and meaningless outside it. The report shows the raw metrics alongside.

Metrics where lower is better are inverted here. Clipping is the only one, and it
carries weight zero by default: on well exposed footage it separates segments on
differences in the fourth decimal. It stays a rejection rule. Motion is not
inverted: still and shaky shots are handled by the rules, and among what survives
more motion is worth more.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from autocut.core.config import ScoringWeights
from autocut.core.manifest import Metrics

# Metric name on Metrics, weight name on ScoringWeights, and whether lower is better.
SCORED_METRICS: tuple[tuple[str, str, bool], ...] = (
    ("sharpness", "sharpness", False),
    ("exposure_clipped", "exposure", True),
    ("motion", "motion", False),
    ("stability", "stability", False),
    ("colorfulness", "colorfulness", False),
)


def rank_normalize(values: np.ndarray) -> np.ndarray:
    """Map values onto 0 to 1 by average rank. Ties share a value; one value gives 0.5."""
    count = int(values.shape[0])
    if count == 0:
        return np.zeros(0)
    if count == 1:
        return np.full(1, 0.5)
    order = np.argsort(values, kind="stable")
    ranks = np.empty(count, dtype=np.float64)
    ranks[order] = np.arange(count, dtype=np.float64)
    # Average the ranks of equal values so identical metrics get identical scores.
    unique, inverse = np.unique(values, return_inverse=True)
    if unique.shape[0] < count:
        sums = np.zeros(unique.shape[0])
        counts = np.zeros(unique.shape[0])
        np.add.at(sums, inverse, ranks)
        np.add.at(counts, inverse, 1.0)
        ranks = (sums / counts)[inverse]
    return ranks / (count - 1)


def score_metrics(entries: Sequence[tuple[str, Metrics]], weights: ScoringWeights) -> list[float]:
    """One composite score in 0 to 1 per segment, in the order given.

    ``entries`` pairs each segment's source class with its metrics. Segments are
    ranked against the other segments of their own class.
    """
    scores = [0.5] * len(entries)
    by_class: dict[str, list[int]] = {}
    for index, (source_class, _) in enumerate(entries):
        by_class.setdefault(source_class, []).append(index)

    for indices in by_class.values():
        group = [entries[index][1] for index in indices]
        for index, score in zip(indices, _composite(group, weights), strict=True):
            scores[index] = score
    return scores


def _composite(metrics: list[Metrics], weights: ScoringWeights) -> list[float]:
    """Weighted mean of the rank normalized metrics of one class."""
    count = len(metrics)
    if count == 0:
        return []
    total_weight = 0.0
    accumulated = np.zeros(count, dtype=np.float64)
    for metric_name, weight_name, lower_is_better in SCORED_METRICS:
        weight = float(getattr(weights, weight_name))
        if weight <= 0:
            continue
        values = np.array([float(getattr(m, metric_name)) for m in metrics], dtype=np.float64)
        normalized = rank_normalize(values)
        if lower_is_better:
            normalized = 1.0 - normalized
        accumulated += weight * normalized
        total_weight += weight
    if total_weight <= 0:
        return [0.5] * count
    return [float(value) for value in accumulated / total_weight]

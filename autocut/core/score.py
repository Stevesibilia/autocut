"""Composite scoring across all segments of one run.

Every metric is rank normalized across the whole project before being weighted,
so one outlier cannot dominate and the diversity and weight sliders in the GUI
behave predictably. The consequence is that scores are comparable within a
manifest and meaningless between manifests; the report shows the raw metrics too.

Metrics where lower is better are inverted here. Clipping always is. Motion is
not: still shots and shaky shots are handled by the rejection rules, and among
what survives more motion is worth more.
"""

from __future__ import annotations

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


def score_metrics(metrics: list[Metrics], weights: ScoringWeights) -> list[float]:
    """One composite score in 0 to 1 per segment, in the order given."""
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

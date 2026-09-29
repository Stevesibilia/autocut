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
from autocut.core.manifest import Manifest, Metrics, Segment

# Metric name on Metrics, weight name on ScoringWeights, and whether lower is better.
SCORED_METRICS: tuple[tuple[str, str, bool], ...] = (
    ("sharpness", "sharpness", False),
    ("exposure_clipped", "exposure", True),
    ("motion", "motion", False),
    ("stability", "stability", False),
    ("colorfulness", "colorfulness", False),
    # Filled by cloud descriptions and absent until they run. A metric no segment of a
    # class has is skipped for that class, so a weight above zero changes nothing until
    # the descriptions exist.
    ("aesthetic", "aesthetic", False),
    # Filled only when providers.faces is on; a class without counts skips it.
    ("faces", "faces", False),
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


def rescore(manifest: Manifest, weights: ScoringWeights) -> int:
    """Recompute every segment's score from the metrics already in the manifest.

    Analysis scores the segments once, with the weights of that run. Moving a weight
    afterwards has to change the scores, and the metrics needed are all in the manifest
    already, so this touches no cache entry and decodes nothing: it is the cheap half
    of what a slider does before selection runs again.

    Returns how many segments were scored. Ranking is per class, as in analysis, which
    is why the class travels with each metric set.
    """
    scored = [
        (_class_of(manifest, segment), segment.metrics)
        for segment in manifest.segments.values()
        if segment.metrics is not None
    ]
    if not scored:
        return 0
    segments = [segment for segment in manifest.segments.values() if segment.metrics is not None]
    for segment, score in zip(segments, score_metrics(scored, weights), strict=True):
        segment.score = score
    return len(segments)


def _class_of(manifest: Manifest, segment: Segment) -> str:
    source = manifest.files.get(segment.file_id)
    return source.source_class if source is not None else "generic"


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
        raw = [getattr(m, metric_name) for m in metrics]
        if any(value is None for value in raw):
            # Partial coverage would rank a described segment against an undescribed
            # one on a number only the first one has, so the metric sits this class out.
            continue
        values = np.array([float(value) for value in raw], dtype=np.float64)
        normalized = rank_normalize(values)
        if lower_is_better:
            normalized = 1.0 - normalized
        accumulated += weight * normalized
        total_weight += weight
    if total_weight <= 0:
        return [0.5] * count
    return [float(value) for value in accumulated / total_weight]

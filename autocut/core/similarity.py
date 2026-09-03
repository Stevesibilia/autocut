"""Pairwise similarity between candidates, from data already in the cache.

Deduplication is a central requirement, not polish: ranking by score alone over a
holiday folder returns ten versions of the same beach. This module estimates how
alike two candidates are without any model, from the thumbnail frame, the GPS fix,
the timestamp and the motion profile.

Signals are a list behind one interface on purpose. Milestone M3 adds CLIP
embeddings as one more signal and nothing in selection changes. A signal that
cannot be computed for a pair, because one of the two has no GPS or no telemetry,
is left out of that pair's mean rather than counted as zero; counting it as zero
would make a missing fix look like evidence of difference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

import numpy as np

from autocut.core.config import AutocutConfig

HASH_BITS = 64
HISTOGRAM_BINS = 8
EARTH_RADIUS_M = 6_371_000.0


@dataclass(slots=True)
class CandidateFeatures:
    """Everything similarity needs about one candidate, precomputed once."""

    segment_id: str
    source_class: str = "generic"
    phash: int | None = None
    histogram: np.ndarray | None = None
    lat: float | None = None
    lon: float | None = None
    timestamp: datetime | None = None
    motion: np.ndarray = field(default_factory=lambda: np.zeros(0))


def perceptual_hash(frame: np.ndarray) -> int:
    """64 bit average hash of a frame, as an integer so distance is a popcount.

    A DCT based hash needs a Pillow image per call and measured worse on the real
    thumbnails, so this is the same idea on the 320 px array already in memory: enough
    to say "same scene". Telling one beach from another beach is what CLIP is for in M3.
    """
    if frame.size == 0:
        return 0
    gray = frame.astype(np.float64).mean(axis=2) if frame.ndim == 3 else frame.astype(np.float64)
    # Average pool to 8x8 without pulling in OpenCV for a thumbnail this small.
    rows = np.array_split(gray, 8, axis=0)
    blocks = [np.array_split(row, 8, axis=1) for row in rows]
    small = np.array([[block.mean() for block in row] for row in blocks])
    mean = small.mean()
    bits = 0
    for value in small.reshape(-1):
        bits = (bits << 1) | int(value > mean)
    return bits


def color_histogram(frame: np.ndarray) -> np.ndarray:
    """Normalized 8x8x8 RGB histogram of a frame."""
    if frame.size == 0 or frame.ndim != 3:
        return np.zeros(HISTOGRAM_BINS**3)
    quantized = (frame.astype(np.int32) * HISTOGRAM_BINS) // 256
    quantized = np.clip(quantized, 0, HISTOGRAM_BINS - 1)
    flat = (
        quantized[:, :, 0] * HISTOGRAM_BINS**2
        + quantized[:, :, 1] * HISTOGRAM_BINS
        + quantized[:, :, 2]
    ).reshape(-1)
    counts = np.bincount(flat, minlength=HISTOGRAM_BINS**3).astype(np.float64)
    total = counts.sum()
    return counts / total if total > 0 else counts


def hash_similarity(first: int, second: int) -> float:
    """1 minus the normalized Hamming distance between two hashes."""
    return 1.0 - (bin(first ^ second).count("1") / HASH_BITS)


def histogram_similarity(first: np.ndarray, second: np.ndarray) -> float:
    """1 minus the normalized chi-square distance between two histograms."""
    if first.size == 0 or first.size != second.size:
        return 0.0
    denominator = first + second
    mask = denominator > 0
    if not mask.any():
        return 1.0
    chi = 0.5 * np.sum(((first[mask] - second[mask]) ** 2) / denominator[mask])
    return float(np.clip(1.0 - chi, 0.0, 1.0))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@runtime_checkable
class SimilaritySignal(Protocol):
    """One way of judging whether two candidates show the same thing."""

    name: str

    def enabled(self, config: AutocutConfig) -> bool:
        """Whether configuration asks for this signal at all."""
        ...

    def available(self, a: CandidateFeatures, b: CandidateFeatures) -> bool:
        """Whether both candidates carry what this signal needs."""
        ...

    def value(self, a: CandidateFeatures, b: CandidateFeatures, config: AutocutConfig) -> float:
        """Similarity in 0 to 1."""
        ...


class VisualSignal:
    """Perceptual hash and colour histogram on the cached thumbnail frame."""

    name = "visual"

    def enabled(self, config: AutocutConfig) -> bool:
        return config.similarity.visual_fallback

    def available(self, a: CandidateFeatures, b: CandidateFeatures) -> bool:
        return (
            a.phash is not None
            and b.phash is not None
            and a.histogram is not None
            and b.histogram is not None
        )

    def value(self, a: CandidateFeatures, b: CandidateFeatures, config: AutocutConfig) -> float:
        assert a.phash is not None and b.phash is not None
        assert a.histogram is not None and b.histogram is not None
        return 0.5 * hash_similarity(a.phash, b.phash) + 0.5 * histogram_similarity(
            a.histogram, b.histogram
        )


class SpatialSignal:
    """Shots taken from the same spot, from the GPS fix."""

    name = "spatial"

    def enabled(self, config: AutocutConfig) -> bool:
        return config.similarity.spatial

    def available(self, a: CandidateFeatures, b: CandidateFeatures) -> bool:
        return None not in (a.lat, a.lon, b.lat, b.lon)

    def value(self, a: CandidateFeatures, b: CandidateFeatures, config: AutocutConfig) -> float:
        assert a.lat is not None and a.lon is not None
        assert b.lat is not None and b.lon is not None
        radius = config.similarity.spatial_radius_m
        if radius <= 0:
            return 0.0
        distance = haversine_m(a.lat, a.lon, b.lat, b.lon)
        return float(np.clip(1.0 - distance / radius, 0.0, 1.0))


class TemporalSignal:
    """Consecutive shots of the same moment, from the absolute timestamp."""

    name = "temporal"

    def enabled(self, config: AutocutConfig) -> bool:
        return config.similarity.temporal

    def available(self, a: CandidateFeatures, b: CandidateFeatures) -> bool:
        return a.timestamp is not None and b.timestamp is not None

    def value(self, a: CandidateFeatures, b: CandidateFeatures, config: AutocutConfig) -> float:
        assert a.timestamp is not None and b.timestamp is not None
        radius = config.similarity.temporal_radius_s
        if radius <= 0:
            return 0.0
        distance = abs((a.timestamp - b.timestamp).total_seconds())
        return float(np.clip(1.0 - distance / radius, 0.0, 1.0))


class MotionSignal:
    """Three identical left to right pans, from the per-frame motion series."""

    name = "motion"

    def enabled(self, config: AutocutConfig) -> bool:
        return config.similarity.motion

    def available(self, a: CandidateFeatures, b: CandidateFeatures) -> bool:
        return a.motion.size > 1 and b.motion.size > 1

    def value(self, a: CandidateFeatures, b: CandidateFeatures, config: AutocutConfig) -> float:
        length = min(a.motion.size, b.motion.size)
        first = _resample(a.motion, length)
        second = _resample(b.motion, length)
        if first.std() == 0 or second.std() == 0:
            # Two flat profiles are the same shape; a flat one and a varying one are not.
            return 1.0 if first.std() == second.std() else 0.0
        correlation = float(np.corrcoef(first, second)[0, 1])
        if math.isnan(correlation):
            return 0.0
        return float(np.clip((correlation + 1.0) / 2.0, 0.0, 1.0))


def _resample(values: np.ndarray, length: int) -> np.ndarray:
    """Two windows can hold a different number of frames; compare their shapes."""
    if values.size == length:
        return values
    positions = np.linspace(0, values.size - 1, length)
    resampled: np.ndarray = np.interp(positions, np.arange(values.size), values)
    return resampled


SIGNALS: tuple[SimilaritySignal, ...] = (
    VisualSignal(),
    SpatialSignal(),
    TemporalSignal(),
    MotionSignal(),
)


def combined_similarity(
    a: CandidateFeatures,
    b: CandidateFeatures,
    config: AutocutConfig,
    signals: tuple[SimilaritySignal, ...] = SIGNALS,
) -> float:
    """Weighted mean of the signals that are both enabled and computable for this pair."""
    total_weight = 0.0
    accumulated = 0.0
    for signal in signals:
        if not signal.enabled(config) or not signal.available(a, b):
            continue
        weight = float(getattr(config.similarity.weights, signal.name, 0.0))
        if weight <= 0:
            continue
        accumulated += weight * signal.value(a, b, config)
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return accumulated / total_weight


class SimilarityMatrix:
    """Pairwise similarity, computed once per pair and kept for the run."""

    def __init__(
        self,
        features: dict[str, CandidateFeatures],
        config: AutocutConfig,
        signals: tuple[SimilaritySignal, ...] = SIGNALS,
    ) -> None:
        self._features = features
        self._config = config
        self._signals = signals
        self._cache: dict[tuple[str, str], float] = {}

    def between(self, first: str, second: str) -> float:
        if first == second:
            return 1.0
        key = (first, second) if first < second else (second, first)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        a, b = self._features.get(key[0]), self._features.get(key[1])
        value = (
            0.0
            if a is None or b is None
            else combined_similarity(a, b, self._config, self._signals)
        )
        self._cache[key] = value
        return value

    def max_against(self, candidate: str, others: list[str]) -> tuple[float, str | None]:
        """Highest similarity to any of ``others``, and which one it was."""
        best, winner = 0.0, None
        for other in others:
            value = self.between(candidate, other)
            if value > best:
                best, winner = value, other
        return best, winner


def assign_clusters(ids: list[str], matrix: SimilarityMatrix, threshold: float) -> dict[str, int]:
    """Single linkage over similarity: one number the user can move, no k to guess."""
    parent = {segment_id: segment_id for segment_id in ids}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index, first in enumerate(ids):
        for second in ids[index + 1 :]:
            if matrix.between(first, second) >= threshold:
                root_a, root_b = find(first), find(second)
                if root_a != root_b:
                    parent[root_b] = root_a

    numbers: dict[str, int] = {}
    clusters: dict[str, int] = {}
    for segment_id in ids:
        root = find(segment_id)
        if root not in numbers:
            numbers[root] = len(numbers)
        clusters[segment_id] = numbers[root]
    return clusters

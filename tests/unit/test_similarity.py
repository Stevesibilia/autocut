"""Similarity signals, their combination and clustering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.similarity import (
    CandidateFeatures,
    MotionSignal,
    SimilarityMatrix,
    SpatialSignal,
    TemporalSignal,
    VisualSignal,
    assign_clusters,
    color_histogram,
    combined_similarity,
    haversine_m,
    perceptual_hash,
)

SIZE = (180, 320, 3)


def beach() -> np.ndarray:
    """Sand below, sky above, with texture so the hash has something to bite on."""
    frame = np.zeros(SIZE, dtype=np.uint8)
    rng = np.random.default_rng(7)
    frame[:90] = np.array([120, 170, 220], dtype=np.uint8)
    frame[90:] = np.array([210, 195, 150], dtype=np.uint8)
    frame += rng.integers(0, 12, size=SIZE, dtype=np.uint8)
    return frame


def beach_panned() -> np.ndarray:
    """The same beach a few degrees over: shifted crop of the same picture."""
    return np.roll(beach(), shift=14, axis=1)


def dinner() -> np.ndarray:
    frame = np.zeros(SIZE, dtype=np.uint8)
    rng = np.random.default_rng(11)
    frame[:] = np.array([70, 45, 35], dtype=np.uint8)
    frame[60:130, 90:230] = np.array([230, 220, 190], dtype=np.uint8)
    frame += rng.integers(0, 20, size=SIZE, dtype=np.uint8)
    return frame


def features(
    segment_id: str,
    frame: np.ndarray | None = None,
    lat: float | None = None,
    lon: float | None = None,
    when: datetime | None = None,
    motion: np.ndarray | None = None,
) -> CandidateFeatures:
    return CandidateFeatures(
        segment_id=segment_id,
        phash=perceptual_hash(frame) if frame is not None else None,
        histogram=color_histogram(frame) if frame is not None else None,
        lat=lat,
        lon=lon,
        timestamp=when,
        motion=motion if motion is not None else np.zeros(0),
    )


def only(config: AutocutConfig, *names: str) -> AutocutConfig:
    """Disable every signal except the named ones, so a test measures one thing."""
    for name in ("visual_fallback", "spatial", "temporal", "motion"):
        setattr(config.similarity, name, name in names)
    return config


def test_same_beach_scores_above_the_duplicate_threshold() -> None:
    signal = VisualSignal()
    a, b = features("a", beach()), features("b", beach_panned())
    assert signal.value(a, b, AutocutConfig()) > 0.7


def test_beach_and_dinner_score_low() -> None:
    signal = VisualSignal()
    a, b = features("a", beach()), features("b", dinner())
    assert signal.value(a, b, AutocutConfig()) < 0.4


def test_visual_signal_needs_both_thumbnails() -> None:
    signal = VisualSignal()
    assert not signal.available(features("a", beach()), features("b"))
    assert signal.available(features("a", beach()), features("b", dinner()))


def test_same_spot() -> None:
    config = AutocutConfig()
    config.similarity.spatial_radius_m = 200.0
    # Roughly ten metres north.
    a = features("a", lat=39.9664, lon=9.6850)
    b = features("b", lat=39.96649, lon=9.6850)
    assert SpatialSignal().value(a, b, config) == pytest.approx(0.95, abs=0.02)


def test_far_apart_scores_zero() -> None:
    config = AutocutConfig()
    a = features("a", lat=39.9664, lon=9.6850)
    b = features("b", lat=40.9664, lon=9.6850)
    assert SpatialSignal().value(a, b, config) == pytest.approx(0.0)


def test_haversine_is_metres() -> None:
    assert haversine_m(39.9664, 9.6850, 39.9664, 9.6850) == pytest.approx(0.0)
    assert haversine_m(0.0, 0.0, 0.0, 1.0) == pytest.approx(111_195, rel=0.01)


def test_consecutive_shots() -> None:
    config = AutocutConfig()
    config.similarity.temporal_radius_s = 600.0
    now = datetime(2025, 7, 14, 13, 37, tzinfo=UTC)
    a = features("a", when=now)
    b = features("b", when=now + timedelta(seconds=30))
    assert TemporalSignal().value(a, b, config) == pytest.approx(0.95)


def test_two_identical_pans() -> None:
    profile = np.array([0.1, 0.3, 0.6, 0.9, 0.6, 0.3])
    a = features("a", motion=profile)
    b = features("b", motion=profile.copy())
    assert MotionSignal().value(a, b, AutocutConfig()) > 0.9


def test_opposite_motion_profiles_score_low() -> None:
    a = features("a", motion=np.array([0.1, 0.3, 0.6, 0.9]))
    b = features("b", motion=np.array([0.9, 0.6, 0.3, 0.1]))
    assert MotionSignal().value(a, b, AutocutConfig()) < 0.1


def test_motion_profiles_of_different_lengths_are_compared_by_shape() -> None:
    a = features("a", motion=np.array([0.1, 0.5, 0.9]))
    b = features("b", motion=np.array([0.1, 0.3, 0.5, 0.7, 0.9]))
    assert MotionSignal().value(a, b, AutocutConfig()) > 0.9


def test_missing_gps_is_excluded_rather_than_counted_as_zero() -> None:
    """A missing fix is not evidence that two clips are different."""
    config = only(AutocutConfig(), "visual_fallback", "temporal")
    now = datetime(2025, 7, 14, 13, 37, tzinfo=UTC)
    a = features("a", beach(), when=now)
    b = features("b", beach_panned(), when=now + timedelta(seconds=30))
    combined = combined_similarity(a, b, config)

    visual = VisualSignal().value(a, b, config)
    temporal = TemporalSignal().value(a, b, config)
    weights = config.similarity.weights
    expected = (weights.visual * visual + weights.temporal * temporal) / (
        weights.visual + weights.temporal
    )
    assert combined == pytest.approx(expected)


def test_all_signals_disabled_gives_zero() -> None:
    config = only(AutocutConfig())
    a, b = features("a", beach()), features("b", beach_panned())
    assert combined_similarity(a, b, config) == 0.0


def test_combined_similarity_stays_in_range() -> None:
    config = AutocutConfig()
    now = datetime(2025, 7, 14, 13, 37, tzinfo=UTC)
    a = features("a", beach(), lat=39.9, lon=9.6, when=now, motion=np.array([0.1, 0.5, 0.9]))
    b = features(
        "b",
        dinner(),
        lat=40.9,
        lon=10.6,
        when=now + timedelta(hours=5),
        motion=np.array([0.9, 0.5, 0.1]),
    )
    value = combined_similarity(a, b, config)
    assert 0.0 <= value <= 1.0


def test_matrix_is_symmetric_and_self_similar() -> None:
    config = AutocutConfig()
    catalogue = {"a": features("a", beach()), "b": features("b", dinner())}
    matrix = SimilarityMatrix(catalogue, config)
    assert matrix.between("a", "a") == 1.0
    assert matrix.between("a", "b") == matrix.between("b", "a")


def test_matrix_reports_the_closest_selected_neighbour() -> None:
    config = only(AutocutConfig(), "visual_fallback")
    catalogue = {
        "a": features("a", beach()),
        "b": features("b", beach_panned()),
        "c": features("c", dinner()),
    }
    matrix = SimilarityMatrix(catalogue, config)
    value, winner = matrix.max_against("a", ["b", "c"])
    assert winner == "b"
    assert value > 0.7
    assert matrix.max_against("a", []) == (0.0, None)


def test_three_similar_shots_share_one_cluster() -> None:
    config = only(AutocutConfig(), "visual_fallback")
    catalogue = {
        "a": features("a", beach()),
        "b": features("b", beach_panned()),
        "c": features("c", np.roll(beach(), shift=26, axis=1)),
        "d": features("d", dinner()),
    }
    matrix = SimilarityMatrix(catalogue, config)
    clusters = assign_clusters(["a", "b", "c", "d"], matrix, threshold=0.7)
    assert clusters["a"] == clusters["b"] == clusters["c"]
    assert clusters["d"] != clusters["a"]
    assert len(set(clusters.values())) == 2


def test_clustering_with_a_threshold_nothing_reaches() -> None:
    config = only(AutocutConfig(), "visual_fallback")
    catalogue = {"a": features("a", beach()), "b": features("b", dinner())}
    matrix = SimilarityMatrix(catalogue, config)
    clusters = assign_clusters(["a", "b"], matrix, threshold=0.99)
    assert clusters["a"] != clusters["b"]


def test_hash_and_histogram_of_an_empty_frame() -> None:
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert perceptual_hash(empty) == 0
    assert color_histogram(empty).sum() == 0

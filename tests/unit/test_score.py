"""Rank normalization and the weighted composite score."""

from __future__ import annotations

import numpy as np
import pytest

from autocut.core.config import ScoringWeights
from autocut.core.manifest import Metrics
from autocut.core.score import rank_normalize, score_metrics


def metrics(
    sharpness: float = 100.0,
    clipped: float = 0.0,
    motion: float = 0.3,
    stability: float = 0.9,
    colorfulness: float = 0.2,
) -> Metrics:
    return Metrics(
        sharpness=sharpness,
        exposure_clipped=clipped,
        motion=motion,
        stability=stability,
        colorfulness=colorfulness,
    )


def test_rank_normalize_spans_zero_to_one() -> None:
    values = rank_normalize(np.array([5.0, 1.0, 3.0]))
    assert values.min() == pytest.approx(0.0)
    assert values.max() == pytest.approx(1.0)
    assert values[1] < values[2] < values[0]


def test_rank_normalize_shares_a_value_between_ties() -> None:
    values = rank_normalize(np.array([2.0, 2.0, 5.0]))
    assert values[0] == pytest.approx(values[1])
    assert values[2] > values[0]


def test_rank_normalize_edge_cases() -> None:
    assert rank_normalize(np.zeros(0)).shape == (0,)
    assert rank_normalize(np.array([7.0])).tolist() == [0.5]


def test_outliers_do_not_dominate() -> None:
    """Rank normalization is why one absurd sharpness value cannot own the ranking."""
    values = rank_normalize(np.array([1.0, 2.0, 3.0, 1_000_000.0]))
    assert values.tolist() == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])


def one_class(batch: list[Metrics], name: str = "drone") -> list[tuple[str, Metrics]]:
    return [(name, item) for item in batch]


def test_scores_stay_inside_zero_to_one() -> None:
    batch = [metrics(sharpness=value) for value in (10.0, 50.0, 900.0)]
    scores = score_metrics(one_class(batch), ScoringWeights())
    assert len(scores) == 3
    assert all(0.0 <= score <= 1.0 for score in scores)


def test_sharper_scores_higher_when_nothing_else_differs() -> None:
    batch = [metrics(sharpness=10.0), metrics(sharpness=900.0)]
    low, high = score_metrics(one_class(batch), ScoringWeights())
    assert high > low


def test_clipping_is_inverted_when_it_carries_weight() -> None:
    batch = [metrics(clipped=0.0), metrics(clipped=0.4)]
    clean, blown = score_metrics(one_class(batch), ScoringWeights(exposure=1.0))
    assert clean > blown


def test_clipping_does_not_rank_by_default() -> None:
    """Weight zero: on well exposed footage this metric only sorts noise."""
    assert ScoringWeights().exposure == 0.0
    batch = [metrics(clipped=0.0), metrics(clipped=0.4)]
    clean, blown = score_metrics(one_class(batch), ScoringWeights())
    assert clean == blown


def test_weights_change_scores_without_touching_metrics() -> None:
    batch = [metrics(sharpness=900.0, colorfulness=0.0), metrics(sharpness=10.0, colorfulness=0.9)]
    balanced = score_metrics(one_class(batch), ScoringWeights())
    color_heavy = score_metrics(
        one_class(batch), ScoringWeights(sharpness=0.0, exposure=0.0, motion=0.0, stability=0.0)
    )
    assert balanced[0] > balanced[1]
    assert color_heavy[1] > color_heavy[0]


def test_all_zero_weights_give_a_neutral_score() -> None:
    weights = ScoringWeights(
        sharpness=0.0, exposure=0.0, motion=0.0, stability=0.0, colorfulness=0.0
    )
    assert score_metrics(one_class([metrics(), metrics()]), weights) == [0.5, 0.5]


def test_empty_input() -> None:
    assert score_metrics([], ScoringWeights()) == []


def test_each_class_is_ranked_against_itself() -> None:
    """The proxy sourced class must not take every top rank of the project."""
    entries: list[tuple[str, Metrics]] = [
        ("actioncam", metrics(sharpness=1300.0)),
        ("actioncam", metrics(sharpness=1900.0)),
        ("drone", metrics(sharpness=500.0)),
        ("drone", metrics(sharpness=900.0)),
    ]
    scores = score_metrics(entries, ScoringWeights())
    best_actioncam, best_drone = scores[1], scores[3]
    # Both classes reach the top of their own range despite disjoint raw sharpness.
    assert best_actioncam == pytest.approx(best_drone)
    assert scores[1] > scores[0]
    assert scores[3] > scores[2]
    # The lowest drone segment outranks the lowest action cam segment nowhere: they
    # are simply not compared.
    assert scores[0] == pytest.approx(scores[2])


def test_a_class_with_one_segment_scores_neutral() -> None:
    entries: list[tuple[str, Metrics]] = [
        ("drone", metrics(sharpness=100.0)),
        ("drone", metrics(sharpness=900.0)),
        ("phone", metrics(sharpness=2500.0)),
    ]
    scores = score_metrics(entries, ScoringWeights())
    assert scores[2] == pytest.approx(0.5)


def test_class_grouping_preserves_input_order() -> None:
    entries: list[tuple[str, Metrics]] = [
        ("drone", metrics(sharpness=100.0)),
        ("actioncam", metrics(sharpness=100.0)),
        ("drone", metrics(sharpness=900.0)),
        ("actioncam", metrics(sharpness=900.0)),
    ]
    scores = score_metrics(entries, ScoringWeights())
    assert len(scores) == 4
    assert scores[0] < scores[2]
    assert scores[1] < scores[3]

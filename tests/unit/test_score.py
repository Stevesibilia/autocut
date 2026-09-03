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


def test_scores_stay_inside_zero_to_one() -> None:
    batch = [metrics(sharpness=value) for value in (10.0, 50.0, 900.0)]
    scores = score_metrics(batch, ScoringWeights())
    assert len(scores) == 3
    assert all(0.0 <= score <= 1.0 for score in scores)


def test_sharper_scores_higher_when_nothing_else_differs() -> None:
    batch = [metrics(sharpness=10.0), metrics(sharpness=900.0)]
    low, high = score_metrics(batch, ScoringWeights())
    assert high > low


def test_clipping_is_inverted() -> None:
    batch = [metrics(clipped=0.0), metrics(clipped=0.4)]
    clean, blown = score_metrics(batch, ScoringWeights())
    assert clean > blown


def test_weights_change_scores_without_touching_metrics() -> None:
    batch = [metrics(sharpness=900.0, colorfulness=0.0), metrics(sharpness=10.0, colorfulness=0.9)]
    balanced = score_metrics(batch, ScoringWeights())
    color_heavy = score_metrics(
        batch, ScoringWeights(sharpness=0.0, exposure=0.0, motion=0.0, stability=0.0)
    )
    assert balanced[0] > balanced[1]
    assert color_heavy[1] > color_heavy[0]


def test_all_zero_weights_give_a_neutral_score() -> None:
    weights = ScoringWeights(
        sharpness=0.0, exposure=0.0, motion=0.0, stability=0.0, colorfulness=0.0
    )
    assert score_metrics([metrics(), metrics()], weights) == [0.5, 0.5]


def test_empty_input() -> None:
    assert score_metrics([], ScoringWeights()) == []

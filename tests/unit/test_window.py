"""Best window search over cached per-frame arrays."""

from __future__ import annotations

import numpy as np
import pytest

from autocut.core.config import ScoringWeights
from autocut.core.window import (
    ClassNorms,
    best_window,
    build_class_norms,
    frame_scores,
    motion_minima,
    snap_start,
)

FPS = 2.0


def grid(count: int) -> np.ndarray:
    return np.arange(count, dtype=np.float64) / FPS


def arrays(sharpness: list[float]) -> dict[str, np.ndarray]:
    count = len(sharpness)
    return {
        "timestamps": grid(count),
        "sharpness": np.array(sharpness, dtype=np.float64),
        "clipping": np.zeros(count),
        "motion": np.full(count, 0.3),
        "stability": np.full(count, 0.9),
        "colorfulness": np.full(count, 0.2),
    }


def test_class_norms_rank_a_frame_against_its_own_class() -> None:
    norms = build_class_norms({"drone": [arrays([10.0, 20.0, 30.0, 40.0])]})
    ranked = norms["drone"].normalize("sharpness", np.array([10.0, 40.0]))
    assert ranked[0] == pytest.approx(0.0)
    assert ranked[1] == pytest.approx(1.0)


def test_class_norms_pool_every_file_of_the_class() -> None:
    norms = build_class_norms({"drone": [arrays([10.0, 20.0]), arrays([30.0, 40.0])]})
    assert norms["drone"].sorted_values["sharpness"].size == 4


def test_a_class_with_one_frame_is_neutral() -> None:
    norms = build_class_norms({"phone": [arrays([5.0])]})
    assert norms["phone"].normalize("sharpness", np.array([5.0])).tolist() == [0.5]


def test_empty_norms_are_neutral() -> None:
    assert ClassNorms().normalize("sharpness", np.array([1.0, 2.0])).tolist() == [0.5, 0.5]


def test_frame_scores_follow_sharpness_when_it_is_the_only_weight() -> None:
    data = arrays([10.0, 20.0, 900.0, 950.0])
    norms = build_class_norms({"drone": [data]})
    weights = ScoringWeights(
        sharpness=1.0, exposure=0.0, motion=0.0, stability=0.0, colorfulness=0.0
    )
    scores = frame_scores(data, norms["drone"], weights)
    assert scores.shape == (4,)
    assert scores[0] < scores[1] < scores[2] < scores[3]


def test_frame_scores_on_an_empty_entry() -> None:
    assert frame_scores({}, ClassNorms(), ScoringWeights()).size == 0


def test_all_zero_weights_give_neutral_frames() -> None:
    data = arrays([10.0, 900.0])
    weights = ScoringWeights(
        sharpness=0.0, exposure=0.0, motion=0.0, stability=0.0, colorfulness=0.0
    )
    assert frame_scores(data, ClassNorms(), weights).tolist() == [0.5, 0.5]


def test_sharp_middle() -> None:
    """Ten seconds, blurred for six, sharp after, three second target."""
    timestamps = grid(20)
    scores = np.where(timestamps < 6.0, 0.1, 0.9)
    center, duration = best_window(scores, timestamps, (0.0, 10.0), 3.0)
    assert duration == pytest.approx(3.0)
    assert 7.5 <= center <= 8.5


def test_short_candidate_keeps_its_whole_span() -> None:
    timestamps = grid(4)
    scores = np.full(4, 0.5)
    center, duration = best_window(scores, timestamps, (0.0, 2.0), 3.0)
    assert center == pytest.approx(1.0)
    assert duration == pytest.approx(2.0)


def test_edge_candidate_ends_flush_with_the_trimmed_end() -> None:
    timestamps = grid(20)
    scores = np.where(timestamps >= 8.5, 1.0, 0.1)
    center, duration = best_window(scores, timestamps, (0.0, 10.0), 3.0)
    assert duration == pytest.approx(3.0)
    # The window ends exactly at the trimmed end, so its centre is half a target before.
    assert center == pytest.approx(8.5)
    assert center + duration / 2 <= 10.0 + 1e-9


def test_window_never_leaves_the_trimmed_span() -> None:
    timestamps = grid(20)
    scores = np.where(timestamps < 2.0, 1.0, 0.1)
    center, duration = best_window(scores, timestamps, (1.0, 9.0), 3.0)
    assert center - duration / 2 >= 1.0 - 1e-9
    assert center + duration / 2 <= 9.0 + 1e-9


def test_a_flat_segment_still_returns_a_valid_window() -> None:
    timestamps = grid(20)
    center, duration = best_window(np.full(20, 0.5), timestamps, (0.0, 10.0), 3.0)
    assert duration == pytest.approx(3.0)
    assert 1.5 <= center <= 8.5


def test_no_frames_falls_back_to_the_midpoint() -> None:
    center, duration = best_window(np.zeros(0), np.zeros(0), (2.0, 8.0), 3.0)
    assert center == pytest.approx(5.0)
    assert duration == pytest.approx(3.0)


def test_a_zero_length_span() -> None:
    center, duration = best_window(np.zeros(0), np.zeros(0), (4.0, 4.0), 3.0)
    assert center == pytest.approx(4.0)
    assert duration == pytest.approx(0.0)


def test_two_candidates_get_windows_of_their_own_length() -> None:
    """The per-clip duration scenario in specs/best-window."""
    timestamps = np.arange(0, 20, 0.5)
    scores = np.linspace(0.0, 1.0, timestamps.size)

    drone_center, drone_duration = best_window(scores, timestamps, (0.0, 20.0), 4.8)
    action_center, action_duration = best_window(scores, timestamps, (0.0, 20.0), 1.6)

    assert drone_duration == pytest.approx(4.8)
    assert action_duration == pytest.approx(1.6)
    assert drone_center != action_center
    # Both end flush with the trimmed end, since the scores rise to the last frame.
    assert drone_center + drone_duration / 2.0 == pytest.approx(20.0)
    assert action_center + action_duration / 2.0 == pytest.approx(20.0)


def test_a_longer_duration_cannot_leave_the_span() -> None:
    timestamps = np.arange(0, 6, 0.5)
    scores = np.ones(timestamps.size)
    center, duration = best_window(scores, timestamps, (1.0, 5.0), 3.5)
    assert duration == pytest.approx(3.5)
    assert center - duration / 2.0 >= 1.0 - 1e-9
    assert center + duration / 2.0 <= 5.0 + 1e-9


# --- motion snap -------------------------------------------------------------


def test_motion_minima_finds_the_dips() -> None:
    motion = np.array([0.5, 0.1, 0.6, 0.7, 0.2, 0.8])
    assert list(motion_minima(motion)) == [1, 4]


def test_a_flat_series_holds_no_minima() -> None:
    """Otherwise every frame of a static shot would look like a boundary."""
    assert motion_minima(np.full(10, 0.5)).size == 0


def test_a_plateau_at_the_bottom_still_counts_once_per_edge() -> None:
    """A dip that levels off is still a dip, at the frames where it turns."""
    found = list(motion_minima(np.array([0.6, 0.2, 0.2, 0.2, 0.7])))
    assert found == [1, 3]


def test_motion_minima_on_a_series_too_short_to_have_any() -> None:
    assert motion_minima(np.array([0.3, 0.1])).size == 0


def test_the_pan_begins() -> None:
    """The scenario in specs/best-window: the window moves back onto the pan's start."""
    timestamps = np.arange(0, 6, 0.1)
    # Motion dips at 2.0 s, where the pan begins, and rises through the pan.
    motion = np.where(np.isclose(timestamps, 2.0), 0.05, 0.5)
    scores = np.full(timestamps.size, 0.8)

    start, snapped = snap_start(2.3, 2.0, scores, timestamps, motion, (0.0, 6.0), 0.5, 0.05)

    assert snapped
    assert start == pytest.approx(2.0)


def test_a_snap_that_would_cost_quality_is_refused() -> None:
    """The scenario in specs/best-window: a 12 percent score loss is not worth it."""
    timestamps = np.arange(0, 6, 0.1)
    motion = np.full(timestamps.size, 0.5)
    motion = np.where(np.isclose(timestamps, 2.0), 0.05, motion)
    # Everything before 2.3 s scores badly, so moving the window back costs too much.
    scores = np.where(timestamps < 2.3, 0.4, 1.0)

    start, snapped = snap_start(2.3, 2.0, scores, timestamps, motion, (0.0, 6.0), 0.5, 0.05)

    assert not snapped
    assert start == pytest.approx(2.3)


def test_a_minimum_outside_the_snap_window_is_ignored() -> None:
    timestamps = np.arange(0, 6, 0.1)
    motion = np.where(np.isclose(timestamps, 1.0), 0.05, 0.5)
    scores = np.full(timestamps.size, 0.8)

    start, snapped = snap_start(2.3, 2.0, scores, timestamps, motion, (0.0, 6.0), 0.5, 0.05)

    assert not snapped
    assert start == pytest.approx(2.3)


def test_a_snap_that_would_leave_the_trimmed_span_is_refused() -> None:
    timestamps = np.arange(0, 6, 0.1)
    motion = np.where(np.isclose(timestamps, 3.4), 0.05, 0.5)
    scores = np.full(timestamps.size, 0.8)

    # A 2.0 s window starting at 3.4 would end at 5.4, past the 5.0 s trimmed end.
    start, snapped = snap_start(3.2, 2.0, scores, timestamps, motion, (0.0, 5.0), 0.5, 0.05)

    assert not snapped
    assert start == pytest.approx(3.2)


def test_the_quietest_qualifying_minimum_wins() -> None:
    timestamps = np.arange(0, 6, 0.1)
    motion = np.full(timestamps.size, 0.5)
    motion = np.where(np.isclose(timestamps, 2.1), 0.20, motion)
    motion = np.where(np.isclose(timestamps, 2.5), 0.05, motion)
    scores = np.full(timestamps.size, 0.8)

    start, snapped = snap_start(2.3, 2.0, scores, timestamps, motion, (0.0, 6.0), 0.5, 0.05)

    assert snapped
    # The deeper dip is the clearer boundary, even though the other one is nearer.
    assert start == pytest.approx(2.5)


def test_a_flat_motion_series_never_snaps() -> None:
    timestamps = np.arange(0, 6, 0.1)
    motion = np.full(timestamps.size, 0.5)
    scores = np.full(timestamps.size, 0.8)
    start, snapped = snap_start(2.3, 2.0, scores, timestamps, motion, (0.0, 6.0), 0.5, 0.05)
    # A static shot has no boundary to land on, so there is nothing to snap to.
    assert not snapped
    assert start == pytest.approx(2.3)


def test_snapping_is_off_when_the_window_is_zero() -> None:
    timestamps = np.arange(0, 6, 0.1)
    motion = np.where(np.isclose(timestamps, 2.0), 0.05, 0.5)
    scores = np.full(timestamps.size, 0.8)
    start, snapped = snap_start(2.3, 2.0, scores, timestamps, motion, (0.0, 6.0), 0.0, 0.05)
    assert not snapped
    assert start == pytest.approx(2.3)


def test_snapping_needs_series_of_matching_length() -> None:
    timestamps = np.arange(0, 6, 0.1)
    scores = np.full(timestamps.size, 0.8)
    start, snapped = snap_start(2.3, 2.0, scores, timestamps, np.zeros(3), (0.0, 6.0), 0.5, 0.05)
    assert not snapped
    assert start == pytest.approx(2.3)

"""Shot detection on sampled frames and per-class trimming."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.probe import probe_file
from autocut.core.sampler import sample_frames
from autocut.core.segment import (
    apply_trims,
    content_series,
    detect_shots,
    detect_shots_pyscenedetect,
    split_on_altitude,
)


def frames_from(values: list[int], size: int = 32) -> np.ndarray:
    return np.stack([np.full((size, size, 3), value, dtype=np.uint8) for value in values])


def _old_content_series(frames: np.ndarray) -> np.ndarray:
    """Verbatim copy of the pre-#82 vectorized implementation, kept only to compare."""
    count = int(frames.shape[0])
    if count < 2:
        return np.zeros(max(count, 0))
    hsv = np.stack([cv2.cvtColor(frame, cv2.COLOR_RGB2HSV) for frame in frames]).astype(np.float64)
    diffs = np.abs(np.diff(hsv, axis=0)).mean(axis=(1, 2, 3)) / 255.0
    return np.concatenate(([0.0], diffs))


def test_pairwise_content_series_matches_the_old_vectorized_implementation() -> None:
    rng = np.random.default_rng(7)
    frames = rng.integers(0, 256, size=(30, 24, 40, 3), dtype=np.uint8)
    new = content_series(frames)
    old = _old_content_series(frames)
    assert np.allclose(new, old, rtol=1e-12, atol=0)


@pytest.mark.ffmpeg
def test_pairwise_content_series_matches_the_old_implementation_on_a_real_fixture(
    synthetic_dir: Path,
) -> None:
    path = synthetic_dir / "multishot.mp4"
    probe = probe_file(path)
    sampled = sample_frames(path, probe, AutocutConfig())
    new = content_series(sampled.frames)
    old = _old_content_series(sampled.frames)
    assert np.allclose(new, old, rtol=1e-12, atol=0)


def test_continuous_shot_yields_one_segment() -> None:
    frames = frames_from([100] * 12)
    timestamps = np.arange(12) / 2.0
    bounds = detect_shots(frames, timestamps, 0.30, 1.0, duration_s=6.0)
    assert bounds == [(0.0, 6.0)]


def test_a_content_change_splits_the_file() -> None:
    frames = frames_from([10] * 6 + [240] * 6)
    timestamps = np.arange(12) / 2.0
    bounds = detect_shots(frames, timestamps, 0.30, 1.0, duration_s=6.0)
    assert len(bounds) == 2
    assert bounds[0] == (0.0, 3.0)
    assert bounds[1] == (3.0, 6.0)


def test_cuts_closer_than_the_minimum_scene_length_are_ignored() -> None:
    frames = frames_from([10, 240, 10, 240, 10, 240, 10, 240, 10, 240, 10, 240])
    timestamps = np.arange(12) / 2.0
    bounds = detect_shots(frames, timestamps, 0.30, 2.0, duration_s=6.0)
    assert len(bounds) <= 3
    for start, stop in bounds:
        assert stop > start


def test_no_frames_still_returns_the_whole_file() -> None:
    empty = np.zeros((0, 4, 4, 3), dtype=np.uint8)
    assert detect_shots(empty, np.zeros(0), 0.3, 1.0, duration_s=4.0) == [(0.0, 4.0)]


def test_phone_clip_trim() -> None:
    config = AutocutConfig()
    assert config.analysis.head_trim_seconds.phone == pytest.approx(0.3)
    trimmed = apply_trims([(0.0, 2.0)], 2.0, "phone", config)
    assert trimmed == [(0.3, 1.7)]


def test_drone_trim_is_a_full_second_each_end() -> None:
    config = AutocutConfig()
    assert apply_trims([(0.0, 20.0)], 20.0, "drone", config) == [(1.0, 19.0)]


def test_a_span_inside_the_trim_region_disappears() -> None:
    config = AutocutConfig()
    assert apply_trims([(0.0, 0.5)], 20.0, "drone", config) == [None]


def test_middle_spans_are_untouched() -> None:
    config = AutocutConfig()
    trimmed = apply_trims([(0.0, 5.0), (5.0, 10.0), (10.0, 20.0)], 20.0, "drone", config)
    assert trimmed == [(1.0, 5.0), (5.0, 10.0), (10.0, 19.0)]


def test_pyscenedetect_without_the_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "scenedetect", None)
    with pytest.raises(RuntimeError, match="scenedetect"):
        detect_shots_pyscenedetect(Path("unused.mp4"), 0.30, 30)


@pytest.mark.ffmpeg
def test_three_shots_in_the_multishot_fixture(synthetic_dir: Path) -> None:
    path = synthetic_dir / "multishot.mp4"
    config = AutocutConfig()
    probe = probe_file(path)
    sampled = sample_frames(path, probe, config)
    bounds = detect_shots(
        sampled.frames,
        sampled.timestamps,
        config.analysis.scene_threshold,
        config.analysis.min_scene_seconds,
        probe.duration_s,
    )
    assert len(bounds) == 3
    assert bounds[0][1] == pytest.approx(3.0, abs=0.5)
    assert bounds[1][1] == pytest.approx(6.0, abs=0.5)


@pytest.mark.ffmpeg
def test_a_continuous_fixture_stays_one_segment(synthetic_dir: Path) -> None:
    path = synthetic_dir / "sharp_pan.mp4"
    config = AutocutConfig()
    probe = probe_file(path)
    sampled = sample_frames(path, probe, config)
    bounds = detect_shots(
        sampled.frames,
        sampled.timestamps,
        config.analysis.scene_threshold,
        config.analysis.min_scene_seconds,
        probe.duration_s,
    )
    assert len(bounds) == 1


def spans(result: list) -> list[tuple[float, float]]:  # type: ignore[type-arg]
    return [span.bounds for span in result]


def test_takeoff_is_split_out_of_a_continuous_shot() -> None:
    heights = [(0.0, 0.5), (1.0, 1.0), (2.0, 3.0), (3.0, 25.0), (4.0, 30.0), (5.0, 2.0)]
    result = split_on_altitude([(0.0, 6.0)], heights, threshold=5.0, grid_s=0.5)
    assert spans(result) == [(0.0, 3.0), (3.0, 5.0), (5.0, 6.0)]
    assert all(span.split_reason == "altitude" for span in result)


def test_a_flight_that_never_goes_low_is_untouched() -> None:
    heights = [(0.0, 25.0), (1.0, 28.0), (2.0, 30.0)]
    result = split_on_altitude([(0.0, 3.0)], heights, threshold=5.0, grid_s=0.5)
    assert spans(result) == [(0.0, 3.0)]
    assert result[0].split_reason is None


def test_a_flight_that_stays_low_is_one_span() -> None:
    heights = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    result = split_on_altitude([(0.0, 3.0)], heights, threshold=5.0, grid_s=0.5)
    assert spans(result) == [(0.0, 3.0)]
    assert result[0].split_reason is None


def test_a_landing_at_the_end_is_split_off() -> None:
    heights = [(0.0, 30.0), (1.0, 28.0), (2.0, 20.0), (3.0, 2.0)]
    result = split_on_altitude([(0.0, 4.0)], heights, threshold=5.0, grid_s=0.5)
    assert spans(result) == [(0.0, 3.0), (3.0, 4.0)]


def test_a_dip_in_the_middle_yields_three_spans() -> None:
    heights = [(0.0, 30.0), (1.0, 2.0), (2.0, 2.5), (3.0, 28.0), (4.0, 30.0)]
    result = split_on_altitude([(0.0, 5.0)], heights, threshold=5.0, grid_s=0.5)
    assert spans(result) == [(0.0, 1.0), (1.0, 3.0), (3.0, 5.0)]


def test_boundaries_snap_to_the_frame_sampling_grid() -> None:
    heights = [(0.0, 1.0), (1.2, 30.0)]
    result = split_on_altitude([(0.0, 3.0)], heights, threshold=5.0, grid_s=0.5)
    # 1.2 s of telemetry lands on the 0.5 s frame grid, so segment bounds stay on it.
    assert spans(result) == [(0.0, 1.0), (1.0, 3.0)]


def test_files_without_height_telemetry_are_untouched() -> None:
    result = split_on_altitude([(0.0, 6.0)], [], threshold=5.0, grid_s=0.5)
    assert spans(result) == [(0.0, 6.0)]
    assert result[0].split_reason is None


def test_the_split_runs_per_shot() -> None:
    heights = [(0.0, 1.0), (1.0, 30.0), (4.0, 30.0), (5.0, 1.0)]
    result = split_on_altitude([(0.0, 3.0), (3.0, 6.0)], heights, threshold=5.0, grid_s=0.5)
    assert spans(result) == [(0.0, 1.0), (1.0, 3.0), (3.0, 5.0), (5.0, 6.0)]


def test_samples_outside_a_shot_do_not_cut_it() -> None:
    heights = [(0.0, 1.0), (9.0, 1.0)]
    result = split_on_altitude([(4.0, 6.0)], heights, threshold=5.0, grid_s=0.5)
    assert spans(result) == [(4.0, 6.0)]

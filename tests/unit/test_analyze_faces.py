"""Face counts in analysis: the segment aggregate, the cache rule and detector failure."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from autocut.core import analyze as analyze_module
from autocut.core.analyze import _aggregate, analyze_file
from autocut.core.cache import CacheEntry, read_entry
from autocut.core.config import AutocutConfig
from autocut.core.faces import FACE_MODEL_ID, FaceDetectionError
from autocut.core.ingest import ingest


def entry_with(counts: list[float] | None) -> CacheEntry:
    arrays = {name: np.ones(len(counts or [0])) for name in ("sharpness", "motion")}
    if counts is not None:
        arrays["faces"] = np.array(counts)
    return CacheEntry(file_key="f", source="original", arrays=arrays, shot_bounds=[])


def aggregate(counts: list[float] | None, indices: list[int], on: bool = True) -> int | None:
    config = AutocutConfig().analysis
    metrics = _aggregate(
        entry_with(counts), np.array(indices, dtype=int), [], (0.0, 4.0), config, on
    )
    return metrics.faces


def test_a_face_turned_away_for_a_moment_keeps_the_count() -> None:
    """Six frames of two people and two of one give two."""
    assert aggregate([2, 2, 2, 1, 2, 2, 1, 2], list(range(8))) == 2


def test_one_false_detection_does_not_raise_the_count() -> None:
    assert aggregate([0, 0, 0, 0, 0, 0, 0, 3], list(range(8))) == 0


def test_an_empty_window_has_zero_faces() -> None:
    assert aggregate([2, 2], []) == 0


def test_no_array_or_detection_off_leaves_the_count_absent() -> None:
    assert aggregate(None, [0]) is None
    assert aggregate([2, 2], [0, 1], on=False) is None


@pytest.fixture
def source(synthetic_dir: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    [found] = [s for s in ingest([synthetic_dir], config) if s.path.name == "sharp_pan.mp4"]
    return found, config


@pytest.mark.ffmpeg
def test_detection_off_stores_no_counts(source) -> None:  # type: ignore[no-untyped-def]
    found, config = source
    result = analyze_file(found, config)
    assert result.entry is not None
    assert "faces" not in result.entry.arrays
    assert result.entry.face_model is None


@pytest.mark.ffmpeg
def test_detection_on_stores_the_counts_and_the_model(  # type: ignore[no-untyped-def]
    source, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, config = source
    config.providers.faces = True
    monkeypatch.setattr(
        analyze_module, "count_faces", lambda frames, cfg: np.full(frames.shape[0], 2.0)
    )

    result = analyze_file(found, config)

    assert result.entry is not None
    assert result.entry.arrays["faces"].tolist() == [2.0] * result.entry.frame_count
    assert result.entry.face_model == FACE_MODEL_ID
    stored = read_entry(found.id, config)
    assert stored is not None
    assert stored.face_model == FACE_MODEL_ID
    assert "faces" in stored.arrays


@pytest.mark.ffmpeg
def test_an_entry_without_counts_is_sampled_again_only_when_detection_is_on(  # type: ignore[no-untyped-def]
    source, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, config = source
    analyze_file(found, config)  # cached without counts

    assert analyze_file(found, config).cached is True

    config.providers.faces = True
    monkeypatch.setattr(
        analyze_module, "count_faces", lambda frames, cfg: np.zeros(frames.shape[0])
    )
    refreshed = analyze_file(found, config)
    assert refreshed.cached is False
    assert refreshed.entry is not None
    assert "faces" in refreshed.entry.arrays

    assert analyze_file(found, config).cached is True
    config.providers.faces = False
    assert analyze_file(found, config).cached is True


@pytest.mark.ffmpeg
def test_a_detector_failure_is_a_warning_and_the_file_is_still_analysed(  # type: ignore[no-untyped-def]
    source, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, config = source
    config.providers.faces = True

    def refuse(frames: np.ndarray, cfg: object) -> np.ndarray:
        raise FaceDetectionError("no model")

    monkeypatch.setattr(analyze_module, "count_faces", refuse)

    result = analyze_file(found, config)

    assert result.error is None
    assert result.entry is not None
    assert "faces" not in result.entry.arrays
    assert result.entry.face_model is None
    assert any("no model" in warning for warning in result.warnings)

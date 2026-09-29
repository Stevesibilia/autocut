"""The bundled YuNet model and the per-frame face counter, with a fake detector."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from autocut.core import faces
from autocut.core.config import AnalysisConfig, AutocutConfig
from autocut.core.faces import FaceDetectionError, count_faces, model_path
from autocut.core.probe import probe_file
from autocut.core.sampler import sample_frames

MODEL_SHA256 = "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0"
HEIGHT, WIDTH = 180, 320


def detection(height: float, score: float) -> list[float]:
    """One YuNet row: x, y, w, h, five landmarks, score."""
    return [10.0, 10.0, 20.0, height, *([0.0] * 10), score]


class FakeDetector:
    """Returns the scripted detections frame by frame and records what it was given."""

    def __init__(self, script: list[list[list[float]] | None]) -> None:
        self.script = script
        self.input_sizes: list[tuple[int, int]] = []
        self.frames: list[np.ndarray] = []

    def setInputSize(self, size: tuple[int, int]) -> None:  # noqa: N802 - the cv2 name
        self.input_sizes.append(size)

    def detect(self, frame: np.ndarray) -> tuple[int, np.ndarray | None]:
        self.frames.append(frame)
        rows = self.script[len(self.frames) - 1]
        return 1, None if rows is None else np.array(rows, dtype=np.float32)


def install(monkeypatch: pytest.MonkeyPatch, detector: Any) -> None:
    monkeypatch.setattr(faces, "_detector", lambda *args: detector)


def frames_of(count: int) -> np.ndarray:
    return np.zeros((count, HEIGHT, WIDTH, 3), dtype=np.uint8)


def test_the_bundled_model_is_the_published_file() -> None:
    assert hashlib.sha256(model_path().read_bytes()).hexdigest() == MODEL_SHA256


def test_the_score_and_height_filters_decide_what_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AnalysisConfig()  # score 0.8, height share 0.06: 10.8 px of 180
    tall = HEIGHT * 0.2
    fake = FakeDetector(
        [
            [detection(tall, 0.95), detection(tall, 0.85)],  # two faces
            [detection(tall, 0.95), detection(tall, 0.5)],  # the weak one drops out
            [detection(5.0, 0.95), detection(tall, 0.95)],  # the tiny one drops out
            None,  # nothing found
        ]
    )
    install(monkeypatch, fake)

    counts = count_faces(frames_of(4), config)

    assert counts.dtype == np.float64
    assert counts.tolist() == [2.0, 1.0, 1.0, 0.0]
    assert fake.input_sizes == [(WIDTH, HEIGHT)]


def test_the_detector_sees_bgr_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeDetector([None])
    install(monkeypatch, fake)
    frame = np.zeros((1, HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[..., 0] = 200  # red channel in the sampler's RGB order

    count_faces(frame, AnalysisConfig())

    assert fake.frames[0][0, 0].tolist() == [0, 0, 200]


def test_no_frames_means_no_detector() -> None:
    assert count_faces(np.zeros((0, HEIGHT, WIDTH, 3), dtype=np.uint8), AnalysisConfig()).size == 0


def test_a_cv2_error_becomes_a_face_detection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        def setInputSize(self, size: tuple[int, int]) -> None:  # noqa: N802
            pass

        def detect(self, frame: np.ndarray) -> Any:
            raise cv2.error("boom")

    install(monkeypatch, Failing())
    with pytest.raises(FaceDetectionError, match="face detection failed"):
        count_faces(frames_of(1), AnalysisConfig())


def test_a_detector_that_cannot_load_is_a_face_detection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: Any) -> Any:
        raise cv2.error("no model")

    faces._detector.cache_clear()
    monkeypatch.setattr(cv2.FaceDetectorYN, "create", refuse)
    try:
        with pytest.raises(FaceDetectionError, match="cannot load"):
            count_faces(frames_of(1), AnalysisConfig())
    finally:
        faces._detector.cache_clear()


@pytest.mark.ffmpeg
def test_the_real_detector_runs_on_sampled_frames(synthetic_dir: Path) -> None:
    path = synthetic_dir / "sharp_pan.mp4"
    sampled = sample_frames(path, probe_file(path), AutocutConfig())

    counts = count_faces(sampled.frames, AutocutConfig().analysis)

    # The fixtures hold no faces to speak of, so only the shape is asserted.
    assert counts.shape == (sampled.count,)
    assert counts.dtype == np.float64
    assert (counts >= 0).all()

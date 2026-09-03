"""Frame metrics on synthetic images, no video decoding involved."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from autocut.core.metrics import (
    center_crop,
    clipping_fraction,
    colorfulness,
    frame_metrics,
    motion_series,
    sharpness,
    stability_series,
)

SIZE = (180, 320)


def noise_frame(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(*SIZE, 3), dtype=np.uint8)


def checkerboard(square: int = 8) -> np.ndarray:
    rows = np.arange(SIZE[0])[:, None] // square
    cols = np.arange(SIZE[1])[None, :] // square
    mask = ((rows + cols) % 2).astype(np.uint8) * 255
    return np.repeat(mask[:, :, None], 3, axis=2)


def flat(value: int) -> np.ndarray:
    return np.full((*SIZE, 3), value, dtype=np.uint8)


def test_blur_lowers_sharpness() -> None:
    sharp = checkerboard()
    blurred = cv2.GaussianBlur(sharp, (0, 0), 8)
    assert sharpness(blurred) < sharpness(sharp)


def test_white_frame_is_fully_clipped() -> None:
    assert clipping_fraction(flat(255)) == pytest.approx(1.0)
    assert clipping_fraction(flat(0)) == pytest.approx(1.0)
    assert clipping_fraction(flat(128)) == pytest.approx(0.0)


def test_partial_overexposure_is_measured() -> None:
    frame = flat(128)
    frame[: int(SIZE[0] * 0.4)] = 255
    assert clipping_fraction(frame) > 0.3


def test_identical_frames_have_zero_motion() -> None:
    frames = np.stack([checkerboard()] * 4)
    motion = motion_series(frames)
    assert motion.shape == (4,)
    assert motion.max() == pytest.approx(0.0)


def test_alternating_frames_have_high_motion_and_low_stability() -> None:
    frames = np.stack([flat(0), flat(255), flat(0), flat(255), flat(0), flat(255)])
    motion = motion_series(frames)
    assert motion.mean() > 0.9
    # Constant large motion is steady, not shaky; irregular motion is what drops stability.
    irregular = np.stack([flat(0), flat(255), flat(255), flat(255), flat(0), flat(255)])
    assert stability_series(motion_series(irregular), 5).mean() < 1.0


def test_stability_is_one_when_the_window_is_too_short() -> None:
    assert stability_series(np.array([0.1, 0.2]), 5).tolist() == [1.0, 1.0]


def test_gray_frame_has_no_color() -> None:
    assert colorfulness(flat(128)) == pytest.approx(0.0, abs=1e-6)
    assert colorfulness(noise_frame()) > 0.0


def test_saturated_frame_is_more_colorful_than_a_muted_one() -> None:
    saturated = np.zeros((*SIZE, 3), dtype=np.uint8)
    saturated[:, :, 0] = 255
    muted = flat(120)
    assert colorfulness(saturated) > colorfulness(muted)


def test_center_crop_keeps_the_middle() -> None:
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    cropped = center_crop(frame, 0.6)
    assert cropped.shape[:2] == (60, 120)
    assert center_crop(frame, 1.0).shape == frame.shape


def test_actioncam_sharpness_ignores_the_edges() -> None:
    """Edge detail must not rescue an out of focus centre on a fisheye lens."""
    frame = cv2.GaussianBlur(checkerboard(), (0, 0), 8)
    frame[:20, :] = checkerboard()[:20, :]
    frame[-20:, :] = checkerboard()[-20:, :]

    frames = np.stack([frame, frame])
    full = frame_metrics(frames, "generic").sharpness[0]
    centered = frame_metrics(frames, "actioncam", center_crop_fraction=0.6).sharpness[0]
    assert centered < full


def test_frame_metrics_arrays_all_have_one_value_per_frame() -> None:
    frames = np.stack([noise_frame(index) for index in range(5)])
    metrics = frame_metrics(frames, "generic")
    assert len(metrics) == 5
    for values in (
        metrics.sharpness,
        metrics.clipping,
        metrics.motion,
        metrics.stability,
        metrics.colorfulness,
    ):
        assert values.shape == (5,)


def test_frame_metrics_on_an_empty_input() -> None:
    metrics = frame_metrics(np.zeros((0, 4, 4, 3), dtype=np.uint8), "generic")
    assert len(metrics) == 0
    assert metrics.motion.shape == (0,)

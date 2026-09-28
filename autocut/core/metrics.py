"""Per-frame quality metrics.

Pure NumPy and OpenCV functions over ``uint8`` RGB arrays, so every metric is
testable on synthetic images without decoding a video. Definitions come from
SPEC.md section 7.3; the tunables they need come from ``AnalysisConfig`` rather
than from literals in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from autocut.core.config import AnalysisConfig, SourceClass

_DEFAULTS = AnalysisConfig()

MAX_LEVEL = 255.0


@dataclass(slots=True)
class FrameMetrics:
    """One value per sampled frame, all arrays the same length."""

    sharpness: np.ndarray
    clipping: np.ndarray
    motion: np.ndarray
    stability: np.ndarray
    colorfulness: np.ndarray

    def __len__(self) -> int:
        return int(self.sharpness.shape[0])


def to_gray(frame: np.ndarray) -> np.ndarray:
    """Luminance of one RGB frame."""
    return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)


def center_crop(frame: np.ndarray, fraction: float) -> np.ndarray:
    """The central ``fraction`` of width and height, used to ignore fisheye edges."""
    if fraction >= 1.0:
        return frame
    height, width = frame.shape[:2]
    crop_h = max(1, int(round(height * fraction)))
    crop_w = max(1, int(round(width * fraction)))
    top = (height - crop_h) // 2
    left = (width - crop_w) // 2
    return frame[top : top + crop_h, left : left + crop_w]


def sharpness(frame: np.ndarray, crop_fraction: float = 1.0) -> float:
    """Variance of the Laplacian: high on detail, low on blur and misfocus."""
    gray = to_gray(center_crop(frame, crop_fraction))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def clipping_fraction(frame: np.ndarray) -> float:
    """Share of luminance pixels crushed to 0 or blown to 255."""
    gray = to_gray(frame)
    clipped = np.count_nonzero((gray == 0) | (gray == 255))
    return float(clipped / gray.size)


def colorfulness(frame: np.ndarray) -> float:
    """Hasler and Süsstrunk colorfulness, normalized so ordinary footage lands near 0 to 1."""
    red, green, blue = (frame[:, :, index].astype(np.float64) for index in range(3))
    rg = red - green
    yb = 0.5 * (red + green) - blue
    std = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2))
    mean = float(np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    return (std + 0.3 * mean) / MAX_LEVEL


def motion_series(frames: np.ndarray) -> np.ndarray:
    """Mean absolute luminance difference to the previous frame, normalized to 0 to 1.

    The array is one value per frame so every metric array lines up. The first
    frame has no predecessor and borrows the second frame's value.

    Walks consecutive frames and keeps only the previous converted frame, rather
    than stacking every frame as float64 at once: with the sampled frames already
    held in memory, this is the difference between one such copy and two (design
    decision 4, issue #82). The formula and dtype are unchanged, so only the
    floating point reduction order can differ from a fully vectorized version.
    """
    count = int(frames.shape[0])
    if count == 0:
        return np.zeros(0)
    if count == 1:
        return np.zeros(1)
    diffs = np.empty(count - 1, dtype=np.float64)
    previous = to_gray(frames[0]).astype(np.float64)
    for index in range(1, count):
        current = to_gray(frames[index]).astype(np.float64)
        diffs[index - 1] = np.abs(current - previous).mean() / MAX_LEVEL
        previous = current
    return np.concatenate(([diffs[0]], diffs))


def stability_series(motion: np.ndarray, window: int = _DEFAULTS.stability_window) -> np.ndarray:
    """One minus the motion variability over a rolling window: 1 is rock steady."""
    count = int(motion.shape[0])
    if count == 0:
        return np.zeros(0)
    if count < window or window < 2:
        return np.ones(count)
    half = window // 2
    values = np.ones(count)
    for index in range(count):
        start = max(0, index - half)
        stop = min(count, index + half + 1)
        chunk = motion[start:stop]
        mean = float(chunk.mean())
        if mean <= 0:
            continue
        values[index] = 1.0 - float(np.clip(chunk.std() / mean, 0.0, 1.0))
    return values


def frame_metrics(
    frames: np.ndarray,
    source_class: SourceClass,
    *,
    center_crop_fraction: float = _DEFAULTS.sharpness_center_crop,
    stability_window: int = _DEFAULTS.stability_window,
) -> FrameMetrics:
    """Every per-frame metric for one file's sampled frames."""
    count = int(frames.shape[0])
    # Action cams are fisheye: the soft edges say nothing about focus, so only the
    # centre of the frame is measured for sharpness.
    crop = center_crop_fraction if source_class == "actioncam" else 1.0
    sharpness_values = np.array([sharpness(frame, crop) for frame in frames], dtype=np.float64)
    clipping_values = np.array([clipping_fraction(frame) for frame in frames], dtype=np.float64)
    colorfulness_values = np.array([colorfulness(frame) for frame in frames], dtype=np.float64)
    motion = motion_series(frames)
    stability = stability_series(motion, stability_window)
    return FrameMetrics(
        sharpness=sharpness_values if count else np.zeros(0),
        clipping=clipping_values if count else np.zeros(0),
        motion=motion,
        stability=stability,
        colorfulness=colorfulness_values if count else np.zeros(0),
    )

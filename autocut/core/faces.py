"""Face counts per sampled frame, from OpenCV's YuNet detector.

Counts only, never identity (ADR 14). The 224 KB model ships inside the package, so
nothing is downloaded and no frame leaves the machine. The sampler hands over RGB
frames and YuNet expects BGR, which is the one conversion this module owns.
"""

from __future__ import annotations

import functools
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from autocut.core.config import AnalysisConfig

FACE_MODEL_ID = "yunet-2026may"
MODEL_FILENAME = "face_detection_yunet_2026may.onnx"


class FaceDetectionError(RuntimeError):
    """The detector could not load or failed on a frame. Analysis carries on without counts."""


def model_path() -> Path:
    """Filesystem path of the bundled model, extracted first when the package is zipped."""
    resource = files("autocut.core").joinpath("models", MODEL_FILENAME)
    with as_file(resource) as path:
        return Path(path)


@functools.cache
def _detector(score_threshold: float, nms_threshold: float, top_k: int) -> Any:
    """One detector per settings tuple and process, reused across files.

    Also the seam the unit tests replace. No backend or target is set: the OpenCV 5
    engine warns that targets are unsupported and picks its own.
    """
    try:
        return cv2.FaceDetectorYN.create(
            str(model_path()), "", (320, 320), score_threshold, nms_threshold, top_k
        )
    except (cv2.error, OSError) as error:
        raise FaceDetectionError(f"cannot load the face detector: {error}") from error


def count_faces(frames: np.ndarray, config: AnalysisConfig) -> np.ndarray:
    """Number of faces on each frame of an ``(N, H, W, 3)`` RGB ``uint8`` array.

    A detection counts when its score reaches ``face_score_threshold`` and its box is at
    least ``face_min_height_share`` of the frame height. Returns ``float64`` of length
    ``N``, like the other per-frame arrays.
    """
    counts = np.zeros(frames.shape[0], dtype=np.float64)
    if frames.shape[0] == 0:
        return counts
    height, width = frames.shape[1:3]
    detector = _detector(config.face_score_threshold, config.face_nms_threshold, config.face_top_k)
    min_height = config.face_min_height_share * height
    try:
        detector.setInputSize((width, height))
        for index, frame in enumerate(frames):
            _, detections = detector.detect(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            if detections is None:
                continue
            # Row layout: x, y, w, h, five landmarks (x, y), score.
            boxes = np.asarray(detections)
            keep = (boxes[:, -1] >= config.face_score_threshold) & (boxes[:, 3] >= min_height)
            counts[index] = float(keep.sum())
    except cv2.error as error:
        raise FaceDetectionError(f"face detection failed: {error}") from error
    return counts

"""Thumbnails and sprite strips for the review report and the GUI.

Hover scrubbing on 4K originals is not attempted (SPEC.md section 6.2): the GUI
scrubs the sprite strip written here, at the same 320 px the analysis sampled.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

THUMBS_DIRNAME = "thumbs"


def thumbs_dir(output_dir: Path) -> Path:
    directory = output_dir / THUMBS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_jpeg(frame: np.ndarray, path: Path, quality: int) -> Path:
    """Write one RGB frame as JPEG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(frame), mode="RGB").save(
        path, format="JPEG", quality=quality
    )
    return path


def build_sprite(frames: np.ndarray, max_frames: int) -> np.ndarray:
    """Lay frames out side by side, sampling evenly when there are too many."""
    count = int(frames.shape[0])
    if count == 0:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    if count > max_frames:
        picks = np.linspace(0, count - 1, max_frames).round().astype(int)
        frames = frames[picks]
    return np.concatenate(list(frames), axis=1)


def write_thumbnail(frame: np.ndarray, segment_id: str, output_dir: Path, quality: int) -> Path:
    """The still shown in the report for one segment."""
    return write_jpeg(frame, thumbs_dir(output_dir) / f"{_safe(segment_id)}.jpg", quality)


def write_sprite(sprite: np.ndarray, segment_id: str, output_dir: Path, quality: int) -> Path:
    """The horizontal strip the GUI scrubs for one segment."""
    return write_jpeg(sprite, thumbs_dir(output_dir) / f"{_safe(segment_id)}_sprite.jpg", quality)


def _safe(segment_id: str) -> str:
    """Segment ids carry a colon, which is not a portable filename character."""
    return segment_id.replace(":", "_")

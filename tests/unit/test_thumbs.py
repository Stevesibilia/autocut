"""Thumbnail and sprite writing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from autocut.core.thumbs import build_sprite, write_sprite, write_thumbnail


def frames(count: int, width: int = 32, height: int = 18) -> np.ndarray:
    if count == 0:
        return np.zeros((0, height, width, 3), dtype=np.uint8)
    return np.stack(
        [np.full((height, width, 3), (index * 20) % 256, dtype=np.uint8) for index in range(count)]
    )


def test_thumbnail_lands_under_thumbs(tmp_path: Path) -> None:
    path = write_thumbnail(frames(1)[0], "abc:0", tmp_path, quality=85)
    assert path.exists()
    assert path.parent == tmp_path / "thumbs"
    # The colon in a segment id is not a portable filename character.
    assert path.name == "abc_0.jpg"
    with Image.open(path) as image:
        assert image.size == (32, 18)


def test_sprite_is_as_wide_as_the_frames_it_holds() -> None:
    sprite = build_sprite(frames(5), max_frames=60)
    assert sprite.shape == (18, 32 * 5, 3)


def test_sprite_is_capped(tmp_path: Path) -> None:
    sprite = build_sprite(frames(200), max_frames=60)
    assert sprite.shape == (18, 32 * 60, 3)
    path = write_sprite(sprite, "abc:1", tmp_path, quality=85)
    with Image.open(path) as image:
        assert image.size == (32 * 60, 18)
    assert path.name == "abc_1_sprite.jpg"


def test_empty_sprite() -> None:
    assert build_sprite(frames(0), max_frames=60).size == 0

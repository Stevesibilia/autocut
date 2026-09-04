"""Building one segment's sprite strip after analysis, from the cache alone."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.cache import CacheEntry, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Segment, SourceFile
from autocut.core.thumbs import sprite_for_segment


def settings(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    return config


def project(tmp_path: Path, span: tuple[float, float] = (0.0, 1.0)) -> tuple[Manifest, Segment]:
    now = datetime.now(UTC)
    out = tmp_path / "edit"
    out.mkdir(exist_ok=True)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=out)
    manifest.files["f0"] = SourceFile(
        id="f0",
        path=tmp_path / "GX010001.MP4",
        source_class="actioncam",
        duration_s=10.0,
        width=1920,
        height=1080,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
    )
    segment = Segment(
        id="f0:0",
        file_id="f0",
        start_s=span[0],
        end_s=span[1],
        trimmed_start_s=span[0],
        trimmed_end_s=span[1],
    )
    manifest.segments[segment.id] = segment
    return manifest, segment


def cached(tmp_path: Path, with_sprites: bool = True, shots: int = 2) -> AutocutConfig:
    """An entry for ``f0`` with two shots, optionally carrying their strips."""
    config = settings(tmp_path)
    sprites = []
    if with_sprites:
        for shot in range(shots):
            # Each strip is a different flat colour, so a test can tell them apart.
            sprites.append(np.full((8, 24, 3), 40 * (shot + 1), dtype=np.uint8))
    write_entry(
        CacheEntry(
            file_key="f0",
            source="original",
            arrays={"timestamps": np.arange(4, dtype=np.float64) / 2.0},
            shot_bounds=[(float(shot), float(shot) + 1.0) for shot in range(shots)],
            sprites=sprites,
        ),
        config,
    )
    return config


def test_the_strip_is_built_from_the_cache_with_no_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario from the modified frame-analysis spec.

    ``subprocess.run`` is made to fail rather than counted: the claim is that no
    process is started at all, and a test that counts calls passes just as well when
    the count is wrong.
    """
    config = cached(tmp_path)
    manifest, segment = project(tmp_path)

    def no_processes(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a process was started: {args!r}")

    monkeypatch.setattr(subprocess, "run", no_processes)
    monkeypatch.setattr(subprocess, "Popen", no_processes)

    path = sprite_for_segment(manifest, segment, config)

    assert path is not None
    assert path.exists()
    assert path.stat().st_size > 0
    assert segment.sprite == path


def test_the_strip_is_recorded_on_the_segment(tmp_path: Path) -> None:
    config = cached(tmp_path)
    manifest, segment = project(tmp_path)
    assert segment.sprite is None

    sprite_for_segment(manifest, segment, config)

    assert segment.sprite is not None
    assert Path(segment.sprite).name == "f0_0_sprite.jpg"


def test_an_existing_strip_is_not_rebuilt(tmp_path: Path) -> None:
    config = cached(tmp_path)
    manifest, segment = project(tmp_path)
    first = sprite_for_segment(manifest, segment, config)
    assert first is not None
    stamp = first.stat().st_mtime_ns

    second = sprite_for_segment(manifest, segment, config)

    assert second == first
    assert first.stat().st_mtime_ns == stamp


def test_a_recorded_strip_whose_file_is_gone_is_written_again(tmp_path: Path) -> None:
    """The global cache outlives project folders, so a cleaned thumbs/ costs nothing."""
    config = cached(tmp_path)
    manifest, segment = project(tmp_path)
    first = sprite_for_segment(manifest, segment, config)
    assert first is not None
    first.unlink()

    again = sprite_for_segment(manifest, segment, config)

    assert again is not None
    assert again.exists()


def test_a_segment_takes_the_strip_of_the_shot_it_sits_in(tmp_path: Path) -> None:
    """An altitude split makes two segments out of one shot; both show that shot."""
    config = cached(tmp_path)
    manifest, second_shot = project(tmp_path, span=(1.2, 1.8))

    path = sprite_for_segment(manifest, second_shot, config)

    assert path is not None
    from PIL import Image

    with Image.open(path) as image:
        pixel = image.convert("RGB").getpixel((2, 2))
    # The second shot's strip, which the fixture filled with 80 rather than 40.
    assert isinstance(pixel, tuple)
    assert abs(pixel[0] - 80) <= 6


def test_no_entry_means_no_strip(tmp_path: Path) -> None:
    config = settings(tmp_path)
    manifest, segment = project(tmp_path)

    assert sprite_for_segment(manifest, segment, config) is None
    assert segment.sprite is None


def test_a_file_analysed_without_sprites_has_nothing_to_build_from(tmp_path: Path) -> None:
    """The honest limit: the entry keeps one frame per shot, not every sampled frame.

    So ``analysis.sprites`` off at analysis time means no strip can be reconstructed,
    and the caller has to fall back to the thumbnail rather than expect a scrub.
    """
    config = cached(tmp_path, with_sprites=False)
    manifest, segment = project(tmp_path)

    assert sprite_for_segment(manifest, segment, config) is None


def test_an_empty_strip_in_the_cache_is_not_written(tmp_path: Path) -> None:
    config = settings(tmp_path)
    write_entry(
        CacheEntry(
            file_key="f0",
            source="original",
            arrays={"timestamps": np.zeros(1)},
            shot_bounds=[(0.0, 1.0)],
            sprites=[np.zeros((0, 0, 3), dtype=np.uint8)],
        ),
        config,
    )
    manifest, segment = project(tmp_path)

    assert sprite_for_segment(manifest, segment, config) is None

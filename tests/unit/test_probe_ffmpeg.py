"""Probing the synthetic fixtures with the real ffprobe binary."""

from __future__ import annotations

from pathlib import Path

import pytest

from autocut.core.probe import probe_file

pytestmark = pytest.mark.ffmpeg


def test_vertical_fixture_has_rotation_side_data(synthetic_dir: Path) -> None:
    probe = probe_file(synthetic_dir / "vertical_rot90.mp4")
    assert probe.ok
    # Stored landscape, displayed vertical, exactly like the Xiaomi clips.
    assert (probe.width, probe.height) == (640, 360)
    assert probe.rotation == -90
    assert probe.is_vertical


def test_hevc_fixture_is_ten_bit(synthetic_dir: Path) -> None:
    probe = probe_file(synthetic_dir / "hevc_10bit.mp4")
    assert probe.ok
    assert probe.codec == "hevc"
    assert probe.pix_fmt == "yuv420p10le"
    assert probe.bit_depth == 10


def test_drone_fixture_exposes_its_subtitle_stream(synthetic_dir: Path) -> None:
    probe = probe_file(synthetic_dir / "drone_embedded_srt.mp4")
    assert probe.ok
    assert [s.codec_name for s in probe.subtitle_streams] == ["mov_text"]

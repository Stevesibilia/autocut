"""Sampler command construction, the software fallback and real pipe reads."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.hwaccel import SOFTWARE, Hwaccel
from autocut.core.probe import ProbeResult, probe_file
from autocut.core.sampler import (
    build_sample_command,
    build_single_frame_command,
    sample_frames,
    sample_size,
)


def probe(width: int = 1920, height: int = 1080, rotation: int = 0) -> ProbeResult:
    return ProbeResult(
        path=Path("clip.mp4"),
        width=width,
        height=height,
        rotation=rotation,
        fps=25.0,
        duration_s=20.0,
        codec="h264",
        pix_fmt="yuv420p",
    )


def test_command_is_an_argument_list_with_the_filters_ffmpeg_needs() -> None:
    command = build_sample_command(Path("/footage/a b.MP4"), 2.0, 320, 180, SOFTWARE)
    assert command[0] == "ffmpeg"
    assert "-hwaccel" not in command
    assert command[command.index("-i") + 1] == "/footage/a b.MP4"
    assert command[command.index("-vf") + 1] == "fps=2,scale=320:180"
    assert command[-4:] == ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"][-4:]
    assert command[-1] == "-"


def test_hwaccel_flags_precede_the_input() -> None:
    vaapi = Hwaccel(method="vaapi", device="/dev/dri/renderD128")
    command = build_sample_command(Path("clip.mp4"), 2.0, 320, 180, vaapi)
    assert command.index("-hwaccel") < command.index("-i")
    assert command[command.index("-hwaccel") + 1] == "vaapi"
    assert command[command.index("-hwaccel_device") + 1] == "/dev/dri/renderD128"


def test_videotoolbox_needs_no_device() -> None:
    command = build_sample_command(Path("clip.mp4"), 2.0, 320, 180, Hwaccel("videotoolbox"))
    assert command[command.index("-hwaccel") + 1] == "videotoolbox"
    assert "-hwaccel_device" not in command


def test_sample_size_uses_display_orientation() -> None:
    assert sample_size(probe(1920, 1080), 320) == (320, 180)
    # Stored landscape, displayed vertical: the long side is the display height.
    assert sample_size(probe(1920, 1080, rotation=-90), 320) == (180, 320)
    assert sample_size(probe(3840, 2160), 320) == (320, 180)


def test_a_single_bad_file_still_retries_in_software(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run level choice is verified, so this is a last resort for one clip."""
    commands: list[list[str]] = []
    frame = b"\x00" * (320 * 180 * 3)

    def fake_read(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
        commands.append(command)
        if "-hwaccel" in command:
            return [], 1, "vaapi device creation failed"
        return [frame, frame], 0, ""

    monkeypatch.setattr("autocut.core.sampler.read_frames", fake_read)
    vaapi = Hwaccel(method="vaapi", device="/dev/dri/renderD128")
    sampled = sample_frames(Path("clip.mp4"), probe(), AutocutConfig(), None, vaapi)

    assert len(commands) == 2
    assert "-hwaccel" in commands[0]
    assert "-hwaccel" not in commands[1]
    assert sampled.count == 2
    assert sampled.hwaccel_used == "none"
    assert any("vaapi" in warning for warning in sampled.warnings)


def test_software_decoding_never_spawns_a_second_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wasted spawn per file is the whole point of issue 3."""
    commands: list[list[str]] = []

    def fake_read(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
        commands.append(command)
        return [], 1, "broken file"

    monkeypatch.setattr("autocut.core.sampler.read_frames", fake_read)
    sampled = sample_frames(Path("clip.mp4"), probe(), AutocutConfig(), None, SOFTWARE)

    # One sampling attempt, then only the single frame fallback. Never a retry of
    # the same software command.
    assert len(commands) == 2
    assert all("-hwaccel" not in command for command in commands)
    assert "-frames:v" in commands[1]
    assert sampled.count == 0


def test_a_working_decoder_is_recorded_on_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
        return [b"\x00" * frame_bytes], 0, ""

    monkeypatch.setattr("autocut.core.sampler.read_frames", fake_read)
    sampled = sample_frames(
        Path("clip.mp4"), probe(), AutocutConfig(), None, Hwaccel("videotoolbox")
    )
    assert sampled.hwaccel_used == "videotoolbox"


def test_proxy_is_sampled_when_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_read(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
        commands.append(command)
        return [b"\x00" * frame_bytes], 0, ""

    monkeypatch.setattr("autocut.core.sampler.read_frames", fake_read)
    sampled = sample_frames(Path("clip.MP4"), probe(), AutocutConfig(), Path("clip.LRF"))
    assert commands[0][commands[0].index("-i") + 1] == "clip.LRF"
    assert sampled.source == "proxy"
    assert sampled.path == Path("clip.LRF")


def test_proxy_ignored_when_proxies_are_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_read(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
        commands.append(command)
        return [b"\x00" * frame_bytes], 0, ""

    monkeypatch.setattr("autocut.core.sampler.read_frames", fake_read)
    config = AutocutConfig()
    config.analysis.use_proxies = False
    sampled = sample_frames(Path("clip.MP4"), probe(), config, Path("clip.LRF"))
    assert commands[0][commands[0].index("-i") + 1] == "clip.MP4"
    assert sampled.source == "original"


@pytest.mark.ffmpeg
def test_sampling_a_real_fixture(synthetic_dir: Path) -> None:
    path = synthetic_dir / "sharp_pan.mp4"
    result = probe_file(path)
    sampled = sample_frames(path, result, AutocutConfig())
    # Six seconds at two frames per second, give or take the last partial frame.
    assert 11 <= sampled.count <= 13
    assert sampled.frames.shape[1:] == (180, 320, 3)
    assert sampled.frames.dtype == np.uint8
    assert sampled.timestamps[1] == pytest.approx(0.5)
    assert sampled.source == "original"


def test_single_frame_command_drops_the_fps_filter() -> None:
    command = build_single_frame_command(Path("clip.mp4"), 320, 180)
    assert command[command.index("-frames:v") + 1] == "1"
    assert command[command.index("-vf") + 1] == "scale=320:180"
    assert "fps=" not in " ".join(command)


def test_a_clip_too_short_for_the_fps_filter_still_yields_one_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Action 4 leaves single frame recordings behind; they must not vanish."""
    commands: list[list[str]] = []

    def fake_read(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
        commands.append(command)
        if "-frames:v" in command:
            return [b"\x00" * frame_bytes], 0, ""
        return [], 0, ""

    monkeypatch.setattr("autocut.core.sampler.read_frames", fake_read)
    sampled = sample_frames(Path("clip.mp4"), probe(), AutocutConfig())

    assert sampled.count == 1
    assert sampled.timestamps.tolist() == [0.0]
    assert any("single frame" in warning for warning in sampled.warnings)
    assert "-frames:v" in commands[-1]


def test_a_file_that_decodes_nothing_at_all_reports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(command: list[str], frame_bytes: int) -> tuple[list[bytes], int, str]:
        return [], 1, "moov atom not found"

    monkeypatch.setattr("autocut.core.sampler.read_frames", fake_read)
    sampled = sample_frames(Path("broken.mp4"), probe(), AutocutConfig())

    assert sampled.count == 0
    assert any("no frames decoded" in warning for warning in sampled.warnings)

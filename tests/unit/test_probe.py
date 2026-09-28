"""Probe parsing against ffprobe JSON captured from the three current device families."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autocut.core.probe import (
    ToolMissingError,
    ffprobe_command,
    parse_probe_json,
    probe_file,
    require_tools,
)

DATA = Path(__file__).resolve().parents[1] / "data" / "ffprobe"


def load(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
    return payload


def test_ffprobe_command_is_an_argument_list() -> None:
    command = ffprobe_command(Path("/footage/a b.MP4"))
    assert command[0] == "ffprobe"
    assert "-print_format" in command and "json" in command
    assert command[-1] == "/footage/a b.MP4"


def test_dji_mini2() -> None:
    probe = parse_probe_json(Path("DJI_0744.MP4"), load("dji_mini2"))
    assert probe.ok
    assert (probe.width, probe.height) == (3840, 2160)
    assert probe.fps == pytest.approx(25.0)
    assert probe.codec == "h264"
    assert probe.bit_depth == 8
    assert probe.rotation == 0
    assert not probe.is_vertical
    assert probe.color_transfer == "bt709"
    assert probe.creation_time is not None
    assert probe.creation_time.isoformat() == "2025-07-14T13:37:23+00:00"
    assert probe.gps is not None
    assert probe.gps.lat == pytest.approx(39.9664)
    assert probe.gps.lon == pytest.approx(9.6850)
    # The Mini 2 carries telemetry as a subtitle stream plus a private data stream.
    assert [s.codec_name for s in probe.subtitle_streams] == ["mov_text"]
    assert probe.subtitle_streams[0].handler_name is not None
    assert "DJI.Subtitle" in probe.subtitle_streams[0].handler_name
    assert len(probe.data_streams) == 1


def test_osmo_action4() -> None:
    probe = parse_probe_json(Path("DJI_0194_D.MP4"), load("dji_osmo_action4"))
    assert probe.ok
    assert (probe.width, probe.height) == (1920, 1080)
    assert probe.fps == pytest.approx(50.0)
    assert probe.codec == "hevc"
    assert probe.pix_fmt == "yuv420p10le"
    assert probe.bit_depth == 10
    assert probe.encoder == "DJI OsmoAction4"
    assert probe.gps is None
    assert probe.has_audio
    # djmd and dbgi are the proprietary streams AutoCut deliberately does not parse.
    assert {s.codec_tag for s in probe.data_streams} >= {"djmd", "dbgi"}
    assert probe.subtitle_streams == []


def test_xiaomi_phone() -> None:
    probe = parse_probe_json(Path("VID_20250720_211104.mp4"), load("xiaomi_redmi_note13"))
    assert probe.ok
    assert (probe.width, probe.height) == (1920, 1080)
    assert probe.rotation == -90
    assert probe.is_vertical
    assert (probe.display_width, probe.display_height) == (1080, 1920)
    assert probe.fps == pytest.approx(30.03, abs=0.05)
    assert probe.make == "Xiaomi"
    assert probe.model == "2312DRA50G"
    assert probe.gps is not None
    assert probe.gps.lat == pytest.approx(39.9268)
    assert probe.gps.lon == pytest.approx(9.6641)


def test_legacy_rotate_tag_maps_onto_side_data_sign() -> None:
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "avg_frame_rate": "30/1",
                "tags": {"rotate": "90"},
            }
        ],
        "format": {"duration": "3.0", "tags": {}},
    }
    probe = parse_probe_json(Path("legacy.mp4"), payload)
    assert probe.rotation == -90
    assert probe.is_vertical


def test_missing_video_stream_is_an_error() -> None:
    payload = {"streams": [{"index": 0, "codec_type": "audio"}], "format": {"tags": {}}}
    probe = parse_probe_json(Path("audio.m4a"), payload)
    assert not probe.ok
    assert probe.error == "no video stream"


@pytest.mark.ffmpeg
def test_ffprobe_failure_is_reported_not_raised(tmp_path: Path) -> None:
    not_a_video = tmp_path / "notes.mp4"
    not_a_video.write_text("this is not a video", encoding="utf-8")
    probe = probe_file(not_a_video)
    assert not probe.ok
    assert probe.error


def test_require_tools_passes_when_everything_is_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    require_tools("ffmpeg", "ffprobe")


def test_require_tools_names_every_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None if name == "ffprobe" else "/usr/bin/x")
    with pytest.raises(ToolMissingError) as excinfo:
        require_tools("ffmpeg", "ffprobe")
    assert "ffprobe" in str(excinfo.value)
    assert "ffmpeg" not in str(excinfo.value)
    assert "autocut doctor" in str(excinfo.value)

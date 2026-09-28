"""Probe parsing against ffprobe JSON captured from the three current device families."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from autocut.core.manifest import GpsPoint, SourceFile, StreamInfo
from autocut.core.probe import (
    ffprobe_command,
    parse_probe_json,
    probe_file,
    probe_from_source,
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


def test_probe_from_source_round_trips_every_field_it_carries() -> None:
    source = SourceFile(
        id="key",
        path=Path("/footage/a.mp4"),
        error=None,
        duration_s=12.5,
        width=1920,
        height=1080,
        rotation=-90,
        fps=29.97,
        codec="hevc",
        pix_fmt="yuv420p10le",
        bit_depth=10,
        creation_time=datetime(2025, 7, 14, 13, 37, tzinfo=UTC),
        make="DJI",
        model="Osmo Action 4",
        gps=GpsPoint(lat=39.9664, lon=9.6850),
        subtitle_streams=[StreamInfo(index=2, codec_type="subtitle", codec_name="mov_text")],
        data_streams=[StreamInfo(index=3, codec_type="data", codec_tag="djmd")],
    )
    probe = probe_from_source(source)
    assert probe.ok
    assert probe.path == source.path
    assert probe.duration_s == source.duration_s
    assert probe.width == source.width
    assert probe.height == source.height
    assert probe.rotation == source.rotation
    assert probe.fps == source.fps
    assert probe.codec == source.codec
    assert probe.pix_fmt == source.pix_fmt
    assert probe.bit_depth == source.bit_depth
    assert probe.creation_time == source.creation_time
    assert probe.make == source.make
    assert probe.model == source.model
    assert probe.gps == source.gps
    assert probe.subtitle_streams == source.subtitle_streams
    assert probe.data_streams == source.data_streams
    # Not carried by SourceFile, so left at the ProbeResult default.
    assert probe.color_transfer is None
    assert probe.encoder is None
    assert probe.has_audio is False


def test_probe_from_source_carries_the_error_through() -> None:
    source = SourceFile(id="key", path=Path("/footage/broken.mp4"), error="ffprobe failed")
    probe = probe_from_source(source)
    assert not probe.ok
    assert probe.error == "ffprobe failed"

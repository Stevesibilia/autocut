"""DJI cue parsing, adapter detection and the manifest summary."""

from __future__ import annotations

from pathlib import Path

import pytest

from autocut.core.probe import probe_file
from autocut.core.telemetry import TelemetrySample, TelemetrySeries, detect_telemetry
from autocut.core.telemetry.dji import (
    DjiSidecarSrtAdapter,
    extract_command,
    looks_like_dji_cue,
    parse_cue,
    parse_srt,
)

CUE = (
    "F/2.8, SS 50.00, ISO 200, EV +1.0, DZOOM 1.000, GPS (9.6850, 39.9664, 18), "
    "D 1.76m, H 22.70m, H.S 0.00m/s, V.S -0.00m/s"
)


def srt_document(heights: list[float]) -> str:
    blocks: list[str] = []
    for index, height in enumerate(heights):
        blocks.append(
            f"{index + 1}\n"
            f"00:00:{index:02d},000 --> 00:00:{index + 1:02d},000\n"
            f"F/2.8, SS 50.00, ISO 200, EV +1.0, DZOOM 1.000, "
            f"GPS (9.6850, 39.9664, 18), D 1.76m, H {height:.2f}m, "
            f"H.S 2.00m/s, V.S 0.00m/s \n"
        )
    return "\n".join(blocks)


def test_cue_from_the_spec() -> None:
    sample = parse_cue(CUE, time_s=0.0)
    assert sample is not None
    assert sample.height_m == pytest.approx(22.70)
    assert sample.speed_h_ms == pytest.approx(0.0)
    assert sample.speed_v_ms == pytest.approx(0.0)
    assert sample.lon == pytest.approx(9.6850)
    assert sample.lat == pytest.approx(39.9664)
    assert sample.gps_alt_m == pytest.approx(18.0)
    assert sample.iso == 200
    assert sample.shutter == pytest.approx(50.0)
    assert sample.ev == pytest.approx(1.0)


def test_unknown_fields_do_not_break_parsing() -> None:
    sample = parse_cue(f"{CUE}, NEWFIELD 3.5, COLORMODE 2", time_s=1.0)
    assert sample is not None
    assert sample.height_m == pytest.approx(22.70)


def test_missing_fields_are_none_never_zero() -> None:
    sample = parse_cue("ISO 100, GPS (9.0, 39.0, 5)", time_s=0.0)
    assert sample is not None
    assert sample.iso == 100
    assert sample.height_m is None
    assert sample.speed_h_ms is None


def test_malformed_cue_is_skipped_with_a_warning() -> None:
    document = (
        "1\n00:00:00,000 --> 00:00:01,000\nnothing useful here\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n" + CUE + "\n"
    )
    series = parse_srt(document, "dji_embedded_srt")
    assert len(series.samples) == 1
    assert series.samples[0].time_s == pytest.approx(1.0)
    assert series.warnings == ["cue 1 could not be parsed"]


def test_cue_signature_detection() -> None:
    assert looks_like_dji_cue(CUE)
    assert not looks_like_dji_cue("Subtitle text, nothing to see")


def test_summary_over_a_series() -> None:
    series = parse_srt(srt_document([0.5, 1.0, 30.0, 2.0]), "dji_embedded_srt")
    summary = series.summary()
    assert summary.sample_count == 4
    assert summary.min_height_m == pytest.approx(0.5)
    assert summary.max_height_m == pytest.approx(30.0)
    assert summary.mean_speed_ms == pytest.approx(2.0)
    assert summary.first_gps is not None
    assert summary.first_gps.lat == pytest.approx(39.9664)


def test_summary_without_samples_is_empty() -> None:
    summary = TelemetrySeries(kind="none").summary()
    assert summary.sample_count == 0
    assert summary.min_height_m is None
    assert summary.mean_speed_ms is None


def test_summary_ignores_samples_without_height() -> None:
    series = TelemetrySeries(
        kind="dji_embedded_srt",
        samples=[TelemetrySample(time_s=0.0), TelemetrySample(time_s=1.0, height_m=4.0)],
    )
    summary = series.summary()
    assert summary.sample_count == 2
    assert summary.min_height_m == pytest.approx(4.0)


def test_extract_command_maps_one_stream_and_never_decodes_video() -> None:
    command = extract_command(Path("/footage/DJI_0744.MP4"), 2)
    assert command[0] == "ffmpeg"
    assert "-map" in command
    assert command[command.index("-map") + 1] == "0:2"
    assert command[-3:] == ["-f", "srt", "-"]


@pytest.mark.ffmpeg
def test_embedded_adapter_on_the_synthetic_drone_fixture(synthetic_dir: Path) -> None:
    path = synthetic_dir / "drone_embedded_srt.mp4"
    probe = probe_file(path)
    kind, series = detect_telemetry(probe, path)
    assert kind == "dji_embedded_srt"
    assert series is not None
    heights = [sample.height_m for sample in series.samples]
    assert heights == pytest.approx([0.5, 1.0, 3.0, 25.0, 30.0, 2.0])
    assert series.samples[0].time_s == pytest.approx(0.0)
    summary = series.summary()
    assert summary.sample_count == 6
    assert summary.min_height_m == pytest.approx(0.5)
    assert summary.max_height_m == pytest.approx(30.0)


@pytest.mark.ffmpeg
def test_sidecar_adapter(synthetic_dir: Path, tmp_path: Path) -> None:
    video = tmp_path / "DJI_0001.MP4"
    video.write_bytes((synthetic_dir / "sharp_pan.mp4").read_bytes())
    (tmp_path / "DJI_0001.SRT").write_text(srt_document([1.0, 12.0]), encoding="utf-8")
    probe = probe_file(video)
    kind, series = detect_telemetry(probe, video)
    assert kind == "dji_sidecar_srt"
    assert series is not None
    assert [s.height_m for s in series.samples] == pytest.approx([1.0, 12.0])


@pytest.mark.ffmpeg
def test_no_telemetry_is_not_an_error(synthetic_dir: Path) -> None:
    path = synthetic_dir / "sharp_pan.mp4"
    kind, series = detect_telemetry(probe_file(path), path)
    assert kind == "none"
    assert series is None


def test_sidecar_detection_ignores_a_non_dji_srt(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    (tmp_path / "clip.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello there\n", encoding="utf-8"
    )
    probe = probe_file(video)
    assert not DjiSidecarSrtAdapter().detect(probe, video)

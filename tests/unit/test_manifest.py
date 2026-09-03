from datetime import UTC, datetime
from pathlib import Path

from autocut.core.manifest import (
    AnalysisRun,
    GpsPoint,
    Manifest,
    Metrics,
    Segment,
    SourceFile,
    TelemetrySummary,
)


def test_manifest_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.files["abc"] = SourceFile(
        id="abc",
        path=Path("/footage/DJI_0001.MP4"),
        duration_s=20.0,
        width=3840,
        height=2160,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
        source_class="drone",
        telemetry="dji_embedded_srt",
    )
    m.segments["abc:0"] = Segment(id="abc:0", file_id="abc", start_s=1.0, end_s=19.0)
    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)
    assert back.files["abc"].source_class == "drone"
    assert back.segments["abc:0"].outcome == "candidate"
    assert not out.with_suffix(".json.tmp").exists()


def test_manifest_roundtrip_with_telemetry_and_analysis(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.files["k"] = SourceFile(
        id="k",
        path=Path("/footage/DJI_0744.MP4"),
        proxy_path=Path("/footage/DJI_0744.LRF"),
        duration_s=20.0,
        width=3840,
        height=2160,
        rotation=-90,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
        source_class="drone",
        class_signal="telemetry",
        telemetry="dji_embedded_srt",
        telemetry_summary=TelemetrySummary(
            sample_count=20,
            min_height_m=0.5,
            max_height_m=30.0,
            mean_speed_ms=2.0,
            first_gps=GpsPoint(lat=39.9664, lon=9.6850, alt_m=18.0),
            warnings=["cue 3 could not be parsed"],
        ),
    )
    m.segments["k:0"] = Segment(
        id="k:0",
        file_id="k",
        start_s=0.0,
        end_s=20.0,
        trimmed_start_s=1.0,
        trimmed_end_s=19.0,
        frame_count=36,
        analyzed_from="proxy",
        metrics=Metrics(
            sharpness=120.0,
            exposure_clipped=0.01,
            motion=0.3,
            stability=0.9,
            colorfulness=0.25,
            min_height_m=22.7,
            mean_speed_ms=1.5,
        ),
        score=0.75,
        outcome="rejected",
        reason="low_altitude",
    )

    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)

    source = back.files["k"]
    assert source.is_vertical
    assert source.telemetry_summary is not None
    assert source.telemetry_summary.max_height_m == 30.0
    assert source.telemetry_summary.first_gps is not None

    segment = back.segments["k:0"]
    assert segment.trimmed_start_s == 1.0
    assert segment.trimmed_end_s == 19.0
    assert segment.frame_count == 36
    assert segment.analyzed_from == "proxy"
    assert segment.reason == "low_altitude"
    assert segment.metrics is not None
    assert segment.metrics.min_height_m == 22.7


def test_analysis_run_defaults_and_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    assert m.analysis == AnalysisRun()
    assert m.analysis.hwaccel == "none"

    m.analysis = AnalysisRun(
        files_analyzed=72, files_from_cache=70, files_failed=1, completed=False, hwaccel="vaapi"
    )
    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)
    assert back.analysis.hwaccel == "vaapi"
    assert back.analysis.files_analyzed == 72
    assert not back.analysis.completed

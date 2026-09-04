import json
from datetime import UTC, datetime
from pathlib import Path

from autocut.core.manifest import (
    AnalysisRun,
    GpsPoint,
    Manifest,
    Metrics,
    Segment,
    SelectionRun,
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


def test_tags_roundtrip_with_their_confidence_and_source(tmp_path: Path) -> None:
    from autocut.core.manifest import Tag

    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.segments["a:0"] = Segment(
        id="a:0",
        file_id="a",
        start_s=0.0,
        end_s=4.0,
        tags=[
            Tag(label="beach", confidence=0.62, source="local", group="subject", primary=True),
            Tag(label="snorkeling", confidence=1.0, source="cloud", primary=True),
        ],
    )
    out = tmp_path / "manifest.json"
    m.save(out)

    back = Manifest.load(out).segments["a:0"]
    assert [tag.label for tag in back.tags] == ["beach", "snorkeling"]
    assert back.tags[0].confidence == 0.62
    assert back.tags[1].source == "cloud"
    # The dominant tag follows confidence, not list order.
    assert back.dominant_tag == "snorkeling"


def test_a_manifest_written_before_tags_had_a_shape_still_opens(tmp_path: Path) -> None:
    """M2 wrote tags as plain strings; those projects have to keep opening."""
    from autocut.core.manifest import Tag

    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.segments["a:0"] = Segment(id="a:0", file_id="a", start_s=0.0, end_s=4.0)
    out = tmp_path / "manifest.json"
    m.save(out)
    legacy = json.loads(out.read_text(encoding="utf-8"))
    legacy["segments"]["a:0"]["tags"] = ["sunset", "beach"]
    out.write_text(json.dumps(legacy), encoding="utf-8")

    back = Manifest.load(out).segments["a:0"]
    assert back.tags == [
        Tag(label="sunset", confidence=1.0, source="local", primary=True),
        Tag(label="beach", confidence=1.0, source="local", primary=True),
    ]
    assert back.dominant_tag == "sunset"


def test_a_segment_without_tags_has_no_dominant_tag(tmp_path: Path) -> None:
    assert Segment(id="a:0", file_id="a", start_s=0.0, end_s=1.0).dominant_tag is None


def test_analysis_run_defaults_and_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    assert m.analysis == AnalysisRun()
    assert m.analysis.hwaccel == "none"
    assert m.analysis.embedding_model == "none"
    assert m.analysis.embedding_device == "none"

    m.analysis = AnalysisRun(
        files_analyzed=72,
        files_from_cache=70,
        files_failed=1,
        completed=False,
        hwaccel="vaapi",
        embedding_model="ViT-B-32/laion2b_s34b_b79k",
        embedding_device="mps",
    )
    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)
    assert back.analysis.hwaccel == "vaapi"
    assert back.analysis.files_analyzed == 72
    assert not back.analysis.completed
    assert back.analysis.embedding_model == "ViT-B-32/laion2b_s34b_b79k"
    assert back.analysis.embedding_device == "mps"


def test_selection_fields_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    assert m.selection == SelectionRun()

    m.segments["k:0"] = Segment(
        id="k:0",
        file_id="k",
        start_s=0.0,
        end_s=20.0,
        trimmed_start_s=1.0,
        trimmed_end_s=19.0,
        best_center_s=8.5,
        target_duration_s=3.0,
        cluster_id=4,
        similarity_to_selected=0.88,
        lost_to="k:1",
        outcome="candidate",
    )
    m.segments["k:1"] = Segment(
        id="k:1", file_id="k", start_s=0.0, end_s=20.0, outcome="selected", order=12
    )
    m.selection = SelectionRun(
        ran_at=now,
        diversity_lambda=0.6,
        max_clips=40,
        target_duration_s=3.0,
        selected=1,
        clusters=7,
    )

    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)

    loser = back.segments["k:0"]
    assert loser.best_center_s == 8.5
    assert loser.target_duration_s == 3.0
    assert loser.cluster_id == 4
    assert loser.similarity_to_selected == 0.88
    assert loser.lost_to == "k:1"

    assert back.segments["k:1"].outcome == "selected"
    assert back.segments["k:1"].order == 12
    assert back.selection.diversity_lambda == 0.6
    assert back.selection.clusters == 7
    assert back.selection.ran_at is not None


def test_duration_fields_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.segments["k:0"] = Segment(
        id="k:0",
        file_id="k",
        start_s=0.0,
        end_s=20.0,
        best_center_s=8.5,
        target_duration_s=4.8,
        duration_reason="hero",
        snapped=True,
        outcome="selected",
        order=1,
    )
    m.selection = SelectionRun(selected=1, total_duration_s=118.4)

    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)

    clip = back.segments["k:0"]
    assert clip.target_duration_s == 4.8
    assert clip.duration_reason == "hero"
    assert clip.snapped is True
    assert back.selection.total_duration_s == 118.4


def test_duration_fields_default_to_unset(tmp_path: Path) -> None:
    """An M2 manifest loads unchanged: the new fields are additive with defaults."""
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.segments["k:0"] = Segment(id="k:0", file_id="k", start_s=0.0, end_s=20.0)

    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)

    assert back.segments["k:0"].duration_reason is None
    assert back.segments["k:0"].snapped is False
    assert back.selection.total_duration_s is None


def test_place_fields_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.segments["k:0"] = Segment(
        id="k:0",
        file_id="k",
        start_s=0.0,
        end_s=20.0,
        place_id=2,
        visit_id=5,
        held_by=["a:0", "b:0", "c:0"],
        reason="place_cap",
    )
    m.segments["k:1"] = Segment(id="k:1", file_id="k", start_s=0.0, end_s=20.0)
    m.selection = SelectionRun(places=9, visits=12)

    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)

    held = back.segments["k:0"]
    assert held.place_id == 2
    assert held.visit_id == 5
    assert held.held_by == ["a:0", "b:0", "c:0"]
    assert held.reason == "place_cap"
    # A candidate without GPS carries no place, which is what keeps caps off it.
    assert back.segments["k:1"].place_id is None
    assert back.segments["k:1"].held_by == []
    assert back.selection.places == 9
    assert back.selection.visits == 12

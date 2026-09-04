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


def test_the_soundtrack_block_round_trips(tmp_path: Path) -> None:
    from autocut.core.manifest import PlaceInfo, PromptVariant, SoundtrackSignals

    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.places["0"] = PlaceInfo(
        place_id=0, lat=40.1, lon=9.6, name="Cala Goloritze", region="Sardegna", segments=7
    )
    m.soundtrack.signals = SoundtrackSignals(
        total_duration_s=76.5,
        clip_count=29,
        energy_curve=[0.1, 0.5, 0.9],
        energy_band="mid",
        peak_third=2,
        dominant_tag="beach",
        dominant_tag_share=0.52,
        tags={"beach": 15},
        captions=["two people snorkeling"],
        class_mix={"actioncam": 0.66},
        time_of_day="daytime",
        place_names=["Cala Goloritze"],
        regions=["Sardegna"],
    )
    m.soundtrack.matched_row = "surf rock"
    m.soundtrack.matched_reason = "dominant tag is beach"
    m.soundtrack.genre = "surf rock"
    m.soundtrack.proposed_bpm = 128.0
    m.soundtrack.beat_distance = 0.0125
    m.soundtrack.refinement = "rejected"
    m.soundtrack.refinement_note = "comma_in_tag"
    m.soundtrack.variants = [
        PromptVariant(
            title="cala goloritze, daytime, surf rock",
            description=(
                "surf rock, twangy guitar, driving drums, sunny, 128 bpm, no vocals, instrumental"
            ),
            structure=["[sparse intro]", "[end]"],
            mood=["sunny"],
            instruments=["twangy guitar", "driving drums"],
        )
    ]
    out = tmp_path / "manifest.json"
    m.save(out)

    back = Manifest.load(out)
    assert back.places["0"].name == "Cala Goloritze"
    assert back.places["0"].label == "Cala Goloritze"
    assert back.soundtrack.signals is not None
    assert back.soundtrack.signals.clip_count == 29
    assert back.soundtrack.signals.place_names == ["Cala Goloritze"]
    assert back.soundtrack.matched_row == "surf rock"
    assert back.soundtrack.proposed_bpm == 128.0
    assert back.soundtrack.beat_distance == 0.0125
    assert back.soundtrack.refinement == "rejected"
    assert len(back.soundtrack.variants) == 1
    assert back.soundtrack.variants[0].source == "template"


def test_the_beat_sync_fields_round_trip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.segments["a:0"] = Segment(
        id="a:0",
        file_id="a",
        start_s=0.0,
        end_s=20.0,
        target_duration_s=2.0,
        duration_reason="beat",
        beats=4,
        final_start_s=9.0,
        final_end_s=11.0,
    )
    m.soundtrack.measured_bpm = 119.8
    m.soundtrack.bpm_override = 120.0
    m.soundtrack.beats_s = [0.0, 0.5, 1.0]
    m.soundtrack.audio_path = Path("/tracks/suno.mp3")
    m.soundtrack.comparison = "agreed"
    m.soundtrack.comparison_note = "measured 119.8 against a proposed 120"
    m.soundtrack.beatmap_path = tmp_path / "beatmap.txt"
    out = tmp_path / "manifest.json"
    m.save(out)

    back = Manifest.load(out)
    segment = back.segments["a:0"]
    assert segment.beats == 4
    assert segment.duration_reason == "beat"
    assert segment.final_start_s == 9.0
    assert segment.final_end_s == 11.0
    assert back.soundtrack.measured_bpm == 119.8
    assert back.soundtrack.bpm_override == 120.0
    assert back.soundtrack.beats_s == [0.0, 0.5, 1.0]
    assert back.soundtrack.comparison == "agreed"
    assert back.soundtrack.beatmap_path is not None


def test_a_segment_before_sync_carries_no_beats() -> None:
    segment = Segment(id="a:0", file_id="a", start_s=0.0, end_s=1.0)

    assert segment.beats is None
    assert segment.final_start_s is None


def test_a_place_without_a_name_falls_back_to_its_number() -> None:
    from autocut.core.manifest import PlaceInfo

    assert PlaceInfo(place_id=3).label == "place 3"


def test_the_cloud_fields_of_a_run_round_trip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    assert m.analysis.cloud_model == "none"
    assert m.analysis.cloud_requests == 0
    assert m.analysis.cloud_cost_usd == 0.0

    m.analysis.cloud_model = "google/gemini-2.5-flash"
    m.analysis.cloud_requests = 60
    m.analysis.cloud_cost_usd = 0.0312
    out = tmp_path / "manifest.json"
    m.save(out)

    back = Manifest.load(out)
    assert back.analysis.cloud_model == "google/gemini-2.5-flash"
    assert back.analysis.cloud_requests == 60
    assert back.analysis.cloud_cost_usd == 0.0312


def test_a_caption_and_a_description_error_round_trip(tmp_path: Path) -> None:
    from autocut.core.manifest import Tag

    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.segments["a:0"] = Segment(
        id="a:0",
        file_id="a",
        start_s=0.0,
        end_s=4.0,
        caption="two people snorkeling over clear turquoise water",
        description_error=None,
        metrics=Metrics(
            sharpness=1.0,
            exposure_clipped=0.0,
            motion=0.2,
            stability=0.9,
            colorfulness=0.3,
            aesthetic=0.7,
        ),
        tags=[Tag(label="snorkeling", confidence=1.0, source="cloud", primary=True)],
    )
    out = tmp_path / "manifest.json"
    m.save(out)

    back = Manifest.load(out).segments["a:0"]
    assert back.caption == "two people snorkeling over clear turquoise water"
    assert back.metrics is not None
    assert back.metrics.aesthetic == 0.7
    assert back.tags[0].source == "cloud"
    assert back.dominant_tag == "snorkeling"


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

"""Report rendering from a manifest fixture."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.manifest import AnalysisRun, Manifest, Metrics, Segment, SourceFile
from autocut.core.report import (
    build_cards,
    build_summary,
    duration_label,
    relative_asset,
    render_report,
    resolve_held_by,
    timecode,
)


def source(
    file_id: str,
    name: str,
    source_class: str,
    signal: str = "telemetry",
    telemetry: str = "none",
) -> SourceFile:
    return SourceFile(
        id=file_id,
        path=Path(f"/footage/{name}"),
        source_class=source_class,  # type: ignore[arg-type]
        class_signal=signal,
        telemetry=telemetry,  # type: ignore[arg-type]
        duration_s=20.0,
        width=1920,
        height=1080,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
    )


def segment(
    segment_id: str,
    file_id: str,
    start: float,
    end: float,
    score: float,
    outcome: str = "candidate",
    reason: str | None = None,
    thumbs: Path | None = None,
    **extra: object,
) -> Segment:
    return Segment(
        id=segment_id,
        file_id=file_id,
        start_s=start,
        end_s=end,
        trimmed_start_s=start,
        trimmed_end_s=end,
        frame_count=int((end - start) * 2),
        analyzed_from="original",
        metrics=Metrics(
            sharpness=128.4,
            exposure_clipped=0.012,
            motion=0.31,
            stability=0.92,
            colorfulness=0.24,
            min_height_m=22.7,
        ),
        score=score,
        outcome=outcome,  # type: ignore[arg-type]
        reason=reason,
        thumbnail=thumbs,
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture
def project(tmp_path: Path) -> Manifest:
    """Three classes, two rejection reasons, one thumbnail on disk."""
    out = tmp_path / "edit"
    (out / "thumbs").mkdir(parents=True)
    (out / "thumbs" / "a_0.jpg").write_bytes(b"\xff\xd8\xff")
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now,
        updated_at=now,
        sources=[Path("/footage")],
        output_dir=out,
        analysis=AnalysisRun(files_analyzed=3, files_from_cache=2),
    )
    manifest.files = {
        "a": source("a", "DJI_0744.MP4", "drone", telemetry="dji_embedded_srt"),
        "b": source("b", "DJI_0194_D.MP4", "actioncam", signal="make_tag"),
        "c": source("c", "VID_0001.mp4", "phone", signal="manufacturer_tag"),
    }
    manifest.segments = {
        "a:0": segment(
            "a:0", "a", 0.0, 3.0, 0.20, "rejected", "low_altitude", split_reason="altitude"
        ),
        "a:1": segment("a:1", "a", 3.0, 19.0, 0.91, thumbs=out / "thumbs" / "a_0.jpg"),
        "b:0": segment("b:0", "b", 1.0, 9.0, 0.55),
        "c:0": segment("c:0", "c", 0.3, 1.0, 0.10, "rejected", "too_short"),
    }
    return manifest


def test_cards_are_chronological_and_numbered(project: Manifest) -> None:
    cards = build_cards(project, Path(project.output_dir))
    assert [card.id for card in cards] == ["a:0", "a:1", "b:0", "c:0"]
    assert [card.index for card in cards] == [1, 2, 3, 4]


def test_card_carries_what_the_reviewer_needs(project: Manifest) -> None:
    cards = {card.id: card for card in build_cards(project, Path(project.output_dir))}
    takeoff = cards["a:0"]
    assert takeoff.file_name == "DJI_0744.MP4"
    assert takeoff.source_class == "drone"
    assert takeoff.class_signal == "telemetry"
    assert takeoff.outcome == "rejected"
    assert takeoff.reason == "low_altitude"
    assert takeoff.split_reason == "altitude"
    assert takeoff.duration_label == "3.0 s"
    assert takeoff.start_label == "0:00.0"
    assert takeoff.end_label == "0:03.0"
    assert takeoff.height_label == "22.7 m"
    assert [metric.label for metric in takeoff.metrics] == [
        "Sharpness",
        "Clipped",
        "Motion",
        "Stability",
        "Color",
    ]


def test_thumbnails_are_relative_to_the_output_folder(project: Manifest) -> None:
    cards = {card.id: card for card in build_cards(project, Path(project.output_dir))}
    assert cards["a:1"].thumbnail == "thumbs/a_0.jpg"
    assert cards["a:0"].thumbnail is None


def test_summary_counts(project: Manifest) -> None:
    out = Path(project.output_dir)
    summary = build_summary(project, build_cards(project, out))
    assert summary.file_count == 3
    assert summary.segment_count == 4
    assert summary.files_per_class == [("drone", 1), ("actioncam", 1), ("phone", 1)]
    assert summary.segments_per_outcome == [("candidate", 2), ("rejected", 2)]
    assert summary.segments_per_reason == [("too_short", 1), ("low_altitude", 1)]
    assert summary.files_from_cache == 2
    # 3.0 + 16.0 + 8.0 + 0.7
    assert summary.analyzed_seconds == pytest.approx(27.7)
    assert summary.analyzed_label == "27.7 s"


def test_filter_choices_only_offer_what_is_present(project: Manifest) -> None:
    out = Path(project.output_dir)
    summary = build_summary(project, build_cards(project, out))
    assert summary.classes == ["drone", "actioncam", "phone"]
    assert "reflex" not in summary.classes
    assert summary.outcomes == ["candidate", "rejected"]
    assert set(summary.reasons) == {"too_short", "low_altitude"}


def test_render_writes_report_next_to_the_manifest(project: Manifest) -> None:
    out = Path(project.output_dir)
    path = render_report(project, out)
    assert path == out / "report.html"
    assert path.exists()


def test_page_is_self_contained(project: Manifest) -> None:
    """No network at all: the folder gets copied to another machine and must still work."""
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert "http://" not in html
    assert "https://" not in html
    assert "<link" not in html
    assert "@font-face" not in html
    # The only asset reference is the thumbnail, and it is relative.
    assert 'src="thumbs/a_0.jpg"' in html
    assert not re.search(r'src="/', html)


def test_page_shows_every_card_with_its_state(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert html.count('class="card') == 4
    assert html.count("is-rejected") >= 2
    assert 'data-reason="low_altitude"' in html
    assert 'data-reason="too_short"' in html
    assert 'data-class="drone"' in html
    assert "DJI_0744.MP4" in html
    assert "0.910" in html


def test_page_offers_the_controls_the_spec_requires(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    for control in ('id="sort"', 'id="klass"', 'id="outcome"', 'id="reason"'):
        assert control in html
    assert '<option value="score">' in html
    assert '<option value="chronological">' in html


def test_header_reports_classes_outcomes_and_cache(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert "Files per class" in html
    assert "Segments per outcome" in html
    assert "Rejections per reason" in html
    assert "2 of 3 read from the analysis cache" in html


def test_cancelled_run_is_called_out(project: Manifest) -> None:
    project.analysis.completed = False
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert "cancelled" in html


def test_failed_files_are_called_out(project: Manifest) -> None:
    project.analysis.files_failed = 2
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert "could not be analyzed" in html


def test_an_empty_manifest_still_renders(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path
    )
    html = render_report(manifest, tmp_path).read_text(encoding="utf-8")
    assert "Review 0 segments from 0 files" in html
    assert "Nothing was rejected." in html


def test_file_names_are_escaped(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path
    )
    # A slash would be swallowed by Path, so the hostile name uses none.
    manifest.files = {"a": source("a", '<img src=x onerror="alert(1)">.mp4', "generic")}
    manifest.segments = {"a:0": segment("a:0", "a", 0.0, 4.0, 0.5)}
    html = render_report(manifest, tmp_path).read_text(encoding="utf-8")
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;.mp4" in html


def test_timecode_and_duration_labels() -> None:
    assert timecode(0.0) == "0:00.0"
    assert timecode(9.25) == "0:09.2"
    assert timecode(75.5) == "1:15.5"
    assert duration_label(27.7) == "27.7 s"
    assert duration_label(605.0) == "10 min 5 s"
    assert duration_label(7325.0) == "2 h 2 min"


def test_assets_outside_the_output_folder_keep_their_path(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "shot.jpg"
    assert relative_asset(outside, tmp_path / "edit") == outside.as_posix()
    assert relative_asset(None, tmp_path) is None


def test_metric_columns_stay_aligned() -> None:
    """Exact zeros keep their decimals, otherwise the metric grid loses its column."""
    from autocut.core.report import _number

    assert _number(0.0) == "0.0000"
    assert _number(0.012) == "0.0120"
    assert _number(1.5) == "1.50"
    assert _number(128.4) == "128"
    assert _number(None) == "n/a"
    assert _number(3) == "3"


def test_selected_card_shows_its_order_and_window(project: Manifest) -> None:
    out = Path(project.output_dir)
    chosen = project.segments["a:1"]
    chosen.outcome = "selected"
    chosen.order = 12
    chosen.best_center_s = 8.0
    chosen.target_duration_s = 3.0
    chosen.cluster_id = 4

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "is-selected" in html
    assert ">012<" in html
    assert "cut 0:06.5" in html
    assert "cluster 4" in html


def test_a_lost_duplicate_names_its_winner(project: Manifest) -> None:
    out = Path(project.output_dir)
    project.segments["a:1"].outcome = "selected"
    project.segments["a:1"].order = 1
    loser = project.segments["b:0"]
    loser.lost_to = "a:1"
    loser.similarity_to_selected = 0.88
    loser.cluster_id = 2

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "Lost to" in html
    assert "a:1" in html
    assert "0.88" in html


def test_selected_cards_lead_the_grid(project: Manifest) -> None:
    """Sorted chronologically, the edit comes first and the rest follows."""
    out = Path(project.output_dir)
    late = project.segments["c:0"]
    late.outcome = "selected"
    late.order = 1

    cards = build_cards(project, out)
    assert cards[0].id == "c:0"
    assert cards[0].outcome == "selected"


def test_summary_counts_the_selection(project: Manifest) -> None:
    out = Path(project.output_dir)
    project.segments["a:1"].outcome = "selected"
    project.segments["a:1"].order = 1
    project.segments["a:1"].cluster_id = 0
    project.segments["b:0"].cluster_id = 1
    project.selection.diversity_lambda = 0.6

    summary = build_summary(project, build_cards(project, out))
    assert summary.selected_count == 1
    assert summary.cluster_count == 2
    assert summary.diversity_lambda == pytest.approx(0.6)

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "Selected" in html
    assert "visual clusters" in html


def test_a_project_without_a_selection_says_so(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert "Nothing selected yet" in html


def test_the_selected_total_is_the_edit_not_the_segments(project: Manifest) -> None:
    """The header counts the windows that will be exported, not the spans they sit in."""
    out = Path(project.output_dir)
    for segment_id in ("a:1", "b:0"):
        chosen = project.segments[segment_id]
        chosen.outcome = "selected"
        chosen.best_center_s = (chosen.start_s + chosen.end_s) / 2.0
        chosen.target_duration_s = 3.0
    project.segments["a:1"].order = 1
    project.segments["b:0"].order = 2

    summary = build_summary(project, build_cards(project, out))
    assert summary.selected_count == 2
    assert summary.selected_seconds == pytest.approx(6.0)
    assert summary.selected_seconds < summary.analyzed_seconds


def test_an_exported_card_links_to_its_file(project: Manifest) -> None:
    out = Path(project.output_dir)
    chosen = project.segments["a:1"]
    chosen.outcome = "selected"
    chosen.order = 1
    chosen.exported_path = out / "_selects" / "001_20260812_drone_clip_3.0s.mp4"
    chosen.export_mode = "precise"

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "001_20260812_drone_clip_3.0s.mp4" in html
    assert 'href="_selects/001_20260812_drone_clip_3.0s.mp4"' in html


def test_the_fast_and_resampled_markers_show_on_the_card(project: Manifest) -> None:
    out = Path(project.output_dir)
    chosen = project.segments["a:1"]
    chosen.outcome = "selected"
    chosen.order = 1
    chosen.exported_path = out / "_selects" / "001_x.mp4"
    chosen.export_mode = "fast"
    chosen.fps_converted = True

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "fast cut" in html
    assert "fps converted" in html


def test_a_failed_export_says_why_on_the_card(project: Manifest) -> None:
    out = Path(project.output_dir)
    chosen = project.segments["a:1"]
    chosen.outcome = "selected"
    chosen.order = 1
    chosen.export_error = "No such file or directory"

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "Export failed" in html
    assert "No such file or directory" in html


def test_the_header_counts_the_export(project: Manifest) -> None:
    out = Path(project.output_dir)
    for index, segment_id in enumerate(("a:1", "b:0"), start=1):
        chosen = project.segments[segment_id]
        chosen.outcome = "selected"
        chosen.order = index
        chosen.exported_path = out / "_selects" / f"00{index}_x.mp4"
    project.segments["b:0"].fps_converted = True
    project.export.target_fps = 25.0
    project.export.mode = "precise"

    summary = build_summary(project, build_cards(project, out))
    assert summary.exported_count == 2
    assert summary.fps_converted_count == 1
    assert summary.export_fps == pytest.approx(25.0)

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "Exported" in html
    assert "precise cut at" in html
    assert "1 resampled from another frame rate" in html


def test_a_project_without_an_export_says_so(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert "Nothing exported yet" in html


def test_a_clip_excluded_by_policy_is_not_styled_as_rejected(project: Manifest) -> None:
    """A vertical clip under the exclude strategy is fine; the policy held it back."""
    out = Path(project.output_dir)
    excluded = project.segments["b:0"]
    excluded.outcome = "candidate"
    excluded.reason = "vertical"

    cards = build_cards(project, out)
    card = next(card for card in cards if card.id == "b:0")
    assert card.excluded is True

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "is-excluded" in html
    assert "tag policy" in html


def test_a_rejected_clip_is_still_styled_as_rejected(project: Manifest) -> None:
    out = Path(project.output_dir)
    cards = build_cards(project, out)
    rejected = next(card for card in cards if card.outcome == "rejected")
    assert rejected.excluded is False


def test_a_selected_card_shows_its_duration_and_reason(project: Manifest) -> None:
    """The duration reason scenario in specs/review-report."""
    out = Path(project.output_dir)
    chosen = project.segments["a:1"]
    chosen.outcome = "selected"
    chosen.order = 12
    chosen.best_center_s = 8.0
    chosen.target_duration_s = 4.8
    chosen.duration_reason = "hero"

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "4.8 s" in html
    assert "hero" in html


def test_a_snapped_card_says_so(project: Manifest) -> None:
    out = Path(project.output_dir)
    chosen = project.segments["a:1"]
    chosen.outcome = "selected"
    chosen.order = 1
    chosen.target_duration_s = 3.0
    chosen.duration_reason = "base"
    chosen.snapped = True

    summary = build_summary(project, build_cards(project, out))
    assert summary.snapped_count == 1

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "snapped" in html


def test_a_card_without_a_duration_shows_neither(project: Manifest) -> None:
    out = Path(project.output_dir)
    cards = build_cards(project, out)
    plain = next(card for card in cards if card.outcome == "candidate")
    assert plain.duration_target_label is None
    assert plain.duration_reason is None
    assert plain.snapped is False


def test_a_card_shows_its_place(project: Manifest) -> None:
    out = Path(project.output_dir)
    project.segments["a:1"].place_id = 2
    project.segments["a:1"].visit_id = 5

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "place 2" in html
    assert 'data-place="2"' in html


def test_a_held_back_card_names_the_clips_that_filled_the_visit(project: Manifest) -> None:
    """The held back card scenario in specs/review-report: orders, not ids."""
    out = Path(project.output_dir)
    for index, segment_id in enumerate(("a:1", "b:0"), start=1):
        chosen = project.segments[segment_id]
        chosen.outcome = "selected"
        chosen.order = index
        chosen.place_id = 0
        chosen.visit_id = 0
    held = project.segments["c:0"]
    held.place_id = 0
    held.visit_id = 0
    held.reason = "place_cap"
    held.held_by = ["a:1", "b:0"]

    cards = build_cards(project, out)
    resolve_held_by(cards)
    card = next(card for card in cards if card.id == "c:0")
    assert card.held_by_label == "001, 002"

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "Its place was filled by" in html
    assert "place_cap" in html


def test_a_held_back_card_falls_back_to_ids(project: Manifest) -> None:
    """A winner with no order yet still has to be named, however plainly."""
    out = Path(project.output_dir)
    held = project.segments["c:0"]
    held.held_by = ["a:1"]
    cards = build_cards(project, out)
    resolve_held_by(cards)
    card = next(card for card in cards if card.id == "c:0")
    assert card.held_by_label == "a:1"


def test_the_header_lists_the_places(project: Manifest) -> None:
    """The places listed scenario in specs/review-report."""
    out = Path(project.output_dir)
    project.segments["a:1"].place_id = 0
    project.segments["a:1"].visit_id = 0
    project.segments["a:1"].outcome = "selected"
    project.segments["a:1"].order = 1
    project.segments["b:0"].place_id = 0
    project.segments["b:0"].visit_id = 1
    project.segments["c:0"].place_id = 1
    project.segments["c:0"].visit_id = 2

    summary = build_summary(project, build_cards(project, out))
    assert [place.place_id for place in summary.places] == [0, 1]
    assert summary.places[0].visits == 2
    assert summary.places[0].selected == 1
    assert summary.places[0].segments == 2
    assert summary.places[1].segments == 1

    html = render_report(project, out).read_text(encoding="utf-8")
    assert "Places" in html
    assert "2 visits" in html


def test_a_project_without_gps_has_no_place_filter(project: Manifest) -> None:
    """Every synthetic clip but one has no position, and the control would be empty."""
    out = Path(project.output_dir)
    summary = build_summary(project, build_cards(project, out))
    assert summary.places == []

    html = render_report(project, out).read_text(encoding="utf-8")
    assert 'id="place"' not in html

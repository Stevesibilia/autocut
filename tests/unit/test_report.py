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


def tagged(project: Manifest) -> Manifest:
    """Two tagged segments and one left ambiguous, so every branch has a card."""
    from autocut.core.manifest import Tag

    ids = list(project.segments)
    project.segments[ids[0]].tags = [
        Tag(label="beach", confidence=0.62, source="local", group="subject", primary=True),
        Tag(label="people", confidence=0.21, source="local", group="subject", primary=True),
    ]
    project.segments[ids[1]].tags = [
        Tag(label="food", confidence=0.55, source="local", group="subject", primary=True)
    ]
    project.segments[ids[2]].tags = []
    return project


def test_a_tagged_card_shows_every_tag_with_its_confidence(project: Manifest) -> None:
    cards = build_cards(tagged(project), Path(project.output_dir))
    card = next(c for c in cards if c.tags)

    assert [tag.label for tag in card.tags] == ["beach", "people"]
    assert [tag.confidence_label for tag in card.tags] == ["0.62", "0.21"]
    assert card.tags[0].dominant
    assert not card.tags[1].dominant


def test_the_tag_keys_hold_whole_labels(project: Manifest) -> None:
    """The filter compares whole labels, so a label with a space must not split."""
    from autocut.core.manifest import Tag

    ids = list(project.segments)
    project.segments[ids[0]].tags = [
        Tag(label="street food", confidence=0.7, source="local", group="subject", primary=True)
    ]
    card = next(c for c in build_cards(project, Path(project.output_dir)) if c.tags)

    assert card.tag_keys == "|street food|"


def test_the_header_counts_segments_carrying_each_tag(project: Manifest) -> None:
    summary = build_summary(tagged(project), build_cards(tagged(project), Path(project.output_dir)))

    assert [(tag.label, tag.segments) for tag in summary.tags] == [
        ("beach", 1),
        ("food", 1),
        ("people", 1),
    ]
    assert summary.tag_names == ["beach", "food", "people"]


def test_a_project_without_tags_offers_no_tag_filter(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")
    assert 'id="tag"' not in html
    assert "<h2>Tags</h2>" not in html


def test_the_page_offers_a_tag_filter_when_something_is_tagged(project: Manifest) -> None:
    html = render_report(tagged(project), Path(project.output_dir)).read_text(encoding="utf-8")

    assert 'id="tag"' in html
    assert "<h2>Tags</h2>" in html
    assert '<option value="beach">beach (1)</option>' in html
    assert 'data-tags="|beach|people|"' in html
    # The filter matches a whole label between the delimiters.
    assert 'dataset.tags.indexOf("|" + wanted.tag + "|")' in html


def test_tags_show_on_the_card_with_their_confidence(project: Manifest) -> None:
    html = render_report(tagged(project), Path(project.output_dir)).read_text(encoding="utf-8")
    assert "tag subject" in html
    assert ">beach<" in html
    assert ">0.62<" in html


def test_a_secondary_tag_is_shown_after_the_subject_and_not_marked(project: Manifest) -> None:
    """The card has to say which tag names the clip, not just list what fired."""
    from autocut.core.manifest import Tag

    ids = list(project.segments)
    project.segments[ids[0]].tags = [
        Tag(label="aerial", confidence=0.58, source="local", group="view", primary=False),
        Tag(label="beach", confidence=0.24, source="local", group="subject", primary=True),
    ]
    card = next(c for c in build_cards(project, Path(project.output_dir)) if c.tags)

    assert [tag.label for tag in card.tags] == ["beach", "aerial"]
    assert [tag.dominant for tag in card.tags] == [True, False]
    assert [tag.group for tag in card.tags] == ["subject", "view"]


def test_the_page_marks_the_tag_that_names_the_clip(project: Manifest) -> None:
    from autocut.core.manifest import Tag

    ids = list(project.segments)
    project.segments[ids[0]].tags = [
        Tag(label="aerial", confidence=0.58, source="local", group="view", primary=False),
        Tag(label="beach", confidence=0.24, source="local", group="subject", primary=True),
    ]
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "subject tag, local, confidence 0.24, names the clip" in html
    assert "view tag, local, confidence 0.58" in html
    # The view tag is styled as the weaker of the two rather than as the dominant one.
    assert 'class="tag subject weak"' in html


def test_a_card_with_only_a_view_tag_has_no_dominant_chip(project: Manifest) -> None:
    from autocut.core.manifest import Tag

    ids = list(project.segments)
    project.segments[ids[0]].tags = [
        Tag(label="aerial", confidence=0.58, source="local", group="view", primary=False)
    ]
    card = next(c for c in build_cards(project, Path(project.output_dir)) if c.tags)

    assert [tag.dominant for tag in card.tags] == [False]


def described(project: Manifest) -> Manifest:
    """One segment with a cloud description, one with only local tags, one with neither."""
    from autocut.core.manifest import Tag

    ids = list(project.segments)
    first = project.segments[ids[0]]
    first.caption = "two people snorkeling over clear turquoise water"
    first.tags = [
        Tag(label="snorkeling", confidence=1.0, source="cloud", primary=True),
        Tag(label="beach", confidence=0.62, source="local", group="subject", primary=True),
    ]
    assert first.metrics is not None
    first.metrics.aesthetic = 0.7
    project.segments[ids[1]].tags = [
        Tag(label="food", confidence=0.55, source="local", group="subject", primary=True)
    ]
    project.analysis.cloud_model = "google/gemini-2.5-flash"
    project.analysis.cloud_requests = 60
    project.analysis.cloud_cost_usd = 0.0312
    return project


def test_a_described_card_carries_its_caption_and_aesthetic(project: Manifest) -> None:
    cards = build_cards(described(project), Path(project.output_dir))
    card = next(c for c in cards if c.caption)

    assert card.caption == "two people snorkeling over clear turquoise water"
    # Stored scaled to 0 to 1, shown as the 1 to 10 the model was asked for.
    assert card.aesthetic_label == "7"


def test_a_cloud_tag_is_distinguished_from_a_local_one(project: Manifest) -> None:
    cards = build_cards(described(project), Path(project.output_dir))
    card = next(c for c in cards if c.caption)

    assert [(tag.label, tag.source) for tag in card.tags] == [
        ("snorkeling", "cloud"),
        ("beach", "local"),
    ]
    assert card.tags[0].dominant
    assert not card.tags[1].dominant


def test_the_page_shows_the_caption_the_aesthetic_and_the_cloud_tag(project: Manifest) -> None:
    html = render_report(described(project), Path(project.output_dir)).read_text(encoding="utf-8")

    assert "two people snorkeling over clear turquoise water" in html
    assert "aesthetic 7" in html
    # A cloud tag reads differently from a local one on the card.
    assert "tag subject cloud" in html
    assert 'class="tag subject weak"' in html


def test_the_header_shows_the_model_the_requests_and_the_cost(project: Manifest) -> None:
    """The scenario from the spec: 60 requests costing 0.0312 USD."""
    html = render_report(described(project), Path(project.output_dir)).read_text(encoding="utf-8")

    assert "<h2>Descriptions</h2>" in html
    assert "google/gemini-2.5-flash" in html
    assert "60 requests" in html
    assert "0.0312" in html


def test_the_header_counts_the_captioned_clips(project: Manifest) -> None:
    summary = build_summary(
        described(project), build_cards(described(project), Path(project.output_dir))
    )

    assert summary.captioned_count == 1
    assert summary.cloud_requests == 60
    assert summary.cloud_cost_usd == 0.0312


def test_a_project_without_descriptions_shows_no_cost_panel(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "<h2>Descriptions</h2>" not in html
    assert (
        build_summary(project, build_cards(project, Path(project.output_dir))).cloud_model is None
    )


def test_a_failed_description_says_so_on_the_card(project: Manifest) -> None:
    ids = list(project.segments)
    project.segments[ids[0]].description_error = "provider returned 503"
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "No description: provider returned 503" in html


def test_a_caption_wins_over_a_stale_error_on_the_card(project: Manifest) -> None:
    """A clip that failed once and succeeded later shows the caption, not the error."""
    ids = list(project.segments)
    project.segments[ids[0]].caption = "a beach at noon"
    project.segments[ids[0]].description_error = None
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "a beach at noon" in html
    assert "No description" not in html


def with_soundtrack(project: Manifest) -> Manifest:
    from autocut.core.manifest import PlaceInfo, PromptVariant

    project.soundtrack.matched_row = "surf rock"
    project.soundtrack.matched_reason = "dominant tag is beach; energy mid"
    project.soundtrack.genre = "surf rock"
    project.soundtrack.proposed_bpm = 128.0
    project.soundtrack.beat_distance = 0.0125
    project.soundtrack.prompt_path = Path(project.output_dir) / "suno-prompt.md"
    project.soundtrack.variants = [
        PromptVariant(title="t", description="d", structure=["[end]"]) for _ in range(3)
    ]
    project.places["0"] = PlaceInfo(
        place_id=0, lat=40.1, lon=9.6, name="Cala Goloritze", region="Sardegna", segments=3
    )
    return project


def test_the_header_shows_the_genre_the_bpm_and_the_prompt_link(project: Manifest) -> None:
    html = render_report(with_soundtrack(project), Path(project.output_dir)).read_text(
        encoding="utf-8"
    )

    assert "<h2>Soundtrack</h2>" in html
    assert "128" in html
    assert "surf rock" in html
    assert "dominant tag is beach" in html
    assert 'href="suno-prompt.md"' in html
    assert "3 prompt variants" in html


def test_the_prompt_link_is_relative_to_the_output_folder(project: Manifest) -> None:
    summary = build_summary(
        with_soundtrack(project),
        build_cards(project, Path(project.output_dir)),
        Path(project.output_dir),
    )

    assert summary.prompt_link == "suno-prompt.md"
    assert summary.proposed_bpm == 128.0
    assert summary.variant_count == 3


def test_a_project_without_a_soundtrack_shows_no_panel(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "<h2>Soundtrack</h2>" not in html


def test_a_geocoded_place_is_named_in_the_header(project: Manifest) -> None:
    """The numeric label is a fallback, not the thing the reader should see."""
    ids = list(project.segments)
    project.segments[ids[0]].place_id = 0
    project.segments[ids[0]].visit_id = 0
    html = render_report(with_soundtrack(project), Path(project.output_dir)).read_text(
        encoding="utf-8"
    )

    assert "Cala Goloritze" in html
    assert "Sardegna" in html


def test_a_kept_clip_is_marked_on_its_card_and_in_the_page(project: Manifest) -> None:
    """A human decision has to be visible in the report the CLI writes, not only in the GUI."""
    first = project.segments[next(iter(project.segments))]
    first.user_decision = "keep"

    cards = build_cards(project, Path(project.output_dir))
    card = next(c for c in cards if c.id == first.id)
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert card.user_decision == "keep"
    assert "user kept" in html


def test_a_user_rejected_clip_is_marked(project: Manifest) -> None:
    """The scenario from the gui-review spec: the report shows what the reviewer threw out."""
    ids = list(project.segments)
    for segment_id in ids[:2]:
        project.segments[segment_id].user_decision = "reject"

    summary = build_summary(project, build_cards(project, Path(project.output_dir)))
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert summary.user_rejected_count == 2
    assert "user rejected" in html


def test_hand_set_bounds_are_shown_with_the_user_reason(project: Manifest) -> None:
    first = project.segments[next(iter(project.segments))]
    first.outcome = "selected"
    first.order = 1
    first.user_start_s = 4.0
    first.user_end_s = 6.5
    first.target_duration_s = 2.5
    first.duration_reason = "user"

    cards = build_cards(project, Path(project.output_dir))
    card = next(c for c in cards if c.id == first.id)
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert card.user_bounds_label == "4.0 to 6.5 s by hand"
    assert card.duration_reason == "user"
    assert "4.0 to 6.5 s by hand" in html
    assert ">user<" in html


def test_a_project_nobody_reviewed_shows_no_review_markers(project: Manifest) -> None:
    summary = build_summary(project, build_cards(project, Path(project.output_dir)))
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert summary.kept_count == 0
    assert summary.user_rejected_count == 0
    assert "user kept" not in html
    assert "user rejected" not in html


def test_the_selection_panel_counts_the_review_decisions(project: Manifest) -> None:
    ids = list(project.segments)
    project.segments[ids[0]].user_decision = "keep"
    project.segments[ids[0]].outcome = "selected"
    project.segments[ids[0]].order = 1
    project.segments[ids[1]].user_decision = "reject"

    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "1 kept and 1 rejected by hand" in html


def synced(project: Manifest) -> Manifest:
    """A project after beat sync: one clip selected, cut to four beats."""
    project.soundtrack.measured_bpm = 119.8
    project.soundtrack.comparison = "agreed"
    project.soundtrack.comparison_note = "measured 119.8 against a proposed 120"
    project.soundtrack.beatmap_path = Path(project.output_dir) / "beatmap.txt"
    first = project.segments[list(project.segments)[0]]
    first.outcome = "selected"
    first.order = 1
    first.best_center_s = 3.0
    first.beats = 4
    first.duration_reason = "beat"
    first.target_duration_s = 2.0
    return project


def test_a_synced_card_shows_its_beat_count(project: Manifest) -> None:
    """The scenario from the modified clip-durations spec: 2.0 s, 4 beats, reason beat."""
    cards = build_cards(synced(project), Path(project.output_dir))
    card = next(c for c in cards if c.beats)

    assert card.beats == 4
    assert card.beats_label == "4 beats"
    assert card.duration_reason == "beat"


def test_a_clamped_clip_shows_no_beat_label(project: Manifest) -> None:
    """A clip the span cut short is not on the beat, so the card must not claim it is."""
    manifest = synced(project)
    first = manifest.segments[list(manifest.segments)[0]]
    first.beats = None
    first.duration_reason = "clamped"
    first.target_duration_s = 0.6

    cards = build_cards(manifest, Path(project.output_dir))
    card = next(c for c in cards if c.order == 1)
    html = render_report(manifest, Path(project.output_dir)).read_text(encoding="utf-8")

    assert card.beats is None
    assert card.beats_label is None
    assert card.duration_reason == "clamped"
    assert " beats<" not in html


def test_the_page_shows_the_beat_count_and_the_reason(project: Manifest) -> None:
    html = render_report(synced(project), Path(project.output_dir)).read_text(encoding="utf-8")

    assert "4 beats" in html
    assert ">beat<" in html


def test_the_header_shows_the_measured_bpm_and_the_comparison(project: Manifest) -> None:
    html = render_report(synced(project), Path(project.output_dir)).read_text(encoding="utf-8")

    assert "<h2>Beat sync</h2>" in html
    assert "120" in html
    assert "against a proposed 120" in html
    assert 'href="beatmap.txt"' in html


def test_the_header_says_when_the_bpm_was_forced(project: Manifest) -> None:
    manifest = synced(project)
    manifest.soundtrack.bpm_override = 124.0
    html = render_report(manifest, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "Cut at 124 bpm as asked" in html


def test_a_project_before_sync_shows_no_beat_panel(project: Manifest) -> None:
    html = render_report(project, Path(project.output_dir)).read_text(encoding="utf-8")

    assert "<h2>Beat sync</h2>" not in html
    summary = build_summary(project, build_cards(project, Path(project.output_dir)))
    assert summary.measured_bpm is None
    assert summary.synced_count == 0

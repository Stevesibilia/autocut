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

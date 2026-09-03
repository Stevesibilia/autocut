"""Render the review report from a manifest.

The report is how scoring weights and rejection thresholds get tuned: the manifest
is the truth but nobody can read it, and the GUI is milestone M5. Everything the
page needs is computed here, so the template stays a layout and holds no logic
worth testing.

The page is deliberately self contained. It has to open from a copied folder on a
machine with no network, which rules out web fonts and any hosted asset; the only
external references are the thumbnails under ``thumbs/``, addressed relatively so
the output folder can move as a whole.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from autocut.core.config import SOURCE_CLASSES
from autocut.core.manifest import Manifest, Segment, SourceFile
from autocut.core.rules import ALL_REASONS, EXCLUSIONS

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "report.html.j2"
REPORT_NAME = "report.html"

# Order the metric grid follows on every card, with the label the user reads.
METRIC_LABELS: tuple[tuple[str, str], ...] = (
    ("sharpness", "Sharpness"),
    ("exposure_clipped", "Clipped"),
    ("motion", "Motion"),
    ("stability", "Stability"),
    ("colorfulness", "Color"),
)


@dataclass(slots=True)
class CardMetric:
    """One metric value as the card shows it."""

    key: str
    label: str
    value: str


@dataclass(slots=True)
class Card:
    """One segment, flattened into everything the template prints."""

    id: str
    index: int
    order: int
    file_name: str
    source_class: str
    class_signal: str
    class_overridden: bool
    telemetry: str
    analyzed_from: str
    split_reason: str | None
    start_s: float
    end_s: float
    duration_s: float
    start_label: str
    end_label: str
    duration_label: str
    score: float | None
    score_label: str
    score_percent: float
    outcome: str
    reason: str | None
    edit_order: int | None
    order_label: str
    window_label: str | None
    window_seconds: float | None
    duration_target_label: str | None
    duration_reason: str | None
    snapped: bool
    place_id: int | None
    place_label: str | None
    visit_id: int | None
    held_by: list[str]
    held_by_label: str | None
    cluster_id: int | None
    lost_to: str | None
    similarity_label: str | None
    excluded: bool
    exported_name: str | None
    exported_link: str | None
    export_mode: str | None
    fps_converted: bool
    export_error: str | None
    thumbnail: str | None
    sprite: str | None
    metrics: list[CardMetric] = field(default_factory=list)
    height_label: str | None = None


@dataclass(slots=True)
class PlaceSummary:
    """One place in the header: how many visits it holds and how many clips it gave."""

    place_id: int
    label: str
    visits: int
    selected: int
    segments: int


@dataclass(slots=True)
class Summary:
    """The counts in the header, all derived from the manifest."""

    file_count: int
    segment_count: int
    files_per_class: list[tuple[str, int]]
    segments_per_outcome: list[tuple[str, int]]
    segments_per_reason: list[tuple[str, int]]
    analyzed_seconds: float
    analyzed_label: str
    files_from_cache: int
    files_failed: int
    completed: bool
    selected_count: int
    cluster_count: int
    diversity_lambda: float | None
    selected_seconds: float
    selected_label: str
    exported_count: int
    snapped_count: int
    places: list[PlaceSummary]
    export_mode: str | None
    export_fps: float | None
    export_failed: int
    fps_converted_count: int
    classes: list[str]
    outcomes: list[str]
    reasons: list[str]


def render_report(manifest: Manifest, out_dir: Path) -> Path:
    """Write ``report.html`` into ``out_dir`` and return its path."""
    cards = build_cards(manifest, out_dir)
    resolve_held_by(cards)
    summary = build_summary(manifest, cards)
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        # select_autoescape matches on the file extension, and this template ends in
        # ".j2", so the default list would leave escaping off and let a file name
        # containing markup through into the page.
        autoescape=select_autoescape(
            enabled_extensions=("html", "xml", "j2"),
            default=True,
            default_for_string=True,
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template(TEMPLATE_NAME)
    html = template.render(summary=summary, cards=cards, sources=manifest.sources)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / REPORT_NAME
    path.write_text(html, encoding="utf-8")
    return path


def build_cards(manifest: Manifest, out_dir: Path) -> list[Card]:
    """One card per segment, in chronological order."""
    file_order = {file_id: position for position, file_id in enumerate(manifest.files)}
    ordered = sorted(
        manifest.segments.values(),
        key=lambda segment: (
            # Selected clips lead, in edit order; the rest follow in capture order.
            0 if segment.outcome == "selected" else 1,
            segment.order if segment.order is not None else 0,
            file_order.get(segment.file_id, 0),
            segment.start_s,
        ),
    )
    cards: list[Card] = []
    for index, segment in enumerate(ordered, start=1):
        source = manifest.files.get(segment.file_id)
        cards.append(_card(segment, source, index, out_dir))
    return cards


def _card(segment: Segment, source: SourceFile | None, index: int, out_dir: Path) -> Card:
    start = segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
    end = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
    duration = max(end - start, 0.0)
    score = segment.score
    metrics: list[CardMetric] = []
    if segment.metrics is not None:
        for key, label in METRIC_LABELS:
            metrics.append(
                CardMetric(key=key, label=label, value=_number(getattr(segment.metrics, key)))
            )
    height = None
    if segment.metrics is not None and segment.metrics.min_height_m is not None:
        height = f"{segment.metrics.min_height_m:.1f} m"
    window = None
    if segment.best_center_s is not None and segment.target_duration_s:
        half = segment.target_duration_s / 2.0
        window = (
            f"{timecode(segment.best_center_s - half)}"
            f"\u2013{timecode(segment.best_center_s + half)}"
        )
    similarity = (
        f"{segment.similarity_to_selected:.2f}"
        if segment.similarity_to_selected is not None
        else None
    )
    return Card(
        id=segment.id,
        index=index,
        order=index,
        file_name=source.path.name if source is not None else segment.file_id,
        source_class=source.source_class if source is not None else "generic",
        class_signal=source.class_signal if source is not None else "default",
        class_overridden=source.class_overridden if source is not None else False,
        telemetry=source.telemetry if source is not None else "none",
        analyzed_from=segment.analyzed_from or "original",
        split_reason=segment.split_reason,
        start_s=start,
        end_s=end,
        duration_s=duration,
        start_label=timecode(start),
        end_label=timecode(end),
        duration_label=f"{duration:.1f} s",
        score=score,
        score_label=f"{score:.3f}" if score is not None else "n/a",
        score_percent=round((score or 0.0) * 100, 1),
        outcome=segment.outcome,
        reason=segment.reason,
        edit_order=segment.order,
        order_label=f"{segment.order:03d}" if segment.order else "",
        window_label=window,
        window_seconds=segment.target_duration_s,
        duration_target_label=(
            f"{segment.target_duration_s:.1f} s" if segment.target_duration_s else None
        ),
        duration_reason=segment.duration_reason,
        snapped=segment.snapped,
        place_id=segment.place_id,
        place_label=f"place {segment.place_id}" if segment.place_id is not None else None,
        visit_id=segment.visit_id,
        held_by=list(segment.held_by),
        held_by_label=None,
        cluster_id=segment.cluster_id,
        lost_to=segment.lost_to,
        similarity_label=similarity,
        excluded=segment.reason in EXCLUSIONS,
        exported_name=segment.exported_path.name if segment.exported_path else None,
        exported_link=relative_asset(segment.exported_path, out_dir),
        export_mode=segment.export_mode,
        fps_converted=segment.fps_converted,
        export_error=segment.export_error,
        thumbnail=relative_asset(segment.thumbnail, out_dir),
        sprite=relative_asset(segment.sprite, out_dir),
        metrics=metrics,
        height_label=height,
    )


def build_places(manifest: Manifest, cards: list[Card]) -> list[PlaceSummary]:
    """The places the footage was shot at, in the order selection numbered them."""
    visits: dict[int, set[int]] = {}
    counts: Counter[int] = Counter()
    chosen: Counter[int] = Counter()
    for segment in manifest.segments.values():
        if segment.place_id is None:
            continue
        counts[segment.place_id] += 1
        if segment.visit_id is not None:
            visits.setdefault(segment.place_id, set()).add(segment.visit_id)
        if segment.outcome == "selected":
            chosen[segment.place_id] += 1
    return [
        PlaceSummary(
            place_id=place_id,
            label=f"place {place_id}",
            visits=len(visits.get(place_id, set())),
            selected=chosen[place_id],
            segments=counts[place_id],
        )
        for place_id in sorted(counts)
    ]


def resolve_held_by(cards: list[Card]) -> None:
    """Name the clips that filled a visit by their edit order, not by their ids.

    A card saying it lost to `a3f9c1:0` tells the reader nothing they can act on. The
    same card saying it lost to clips 030, 031 and 032 points at three cards on the
    same page.
    """
    orders = {card.id: card.order_label for card in cards if card.order_label}
    for card in cards:
        if not card.held_by:
            continue
        named = [orders.get(segment_id) or segment_id for segment_id in card.held_by]
        card.held_by_label = ", ".join(named)


def build_summary(manifest: Manifest, cards: list[Card]) -> Summary:
    """Header counts. Every filter dropdown is built from the values actually present."""
    per_class = Counter(source.source_class for source in manifest.files.values())
    per_outcome = Counter(card.outcome for card in cards)
    per_reason = Counter(card.reason for card in cards if card.reason)
    analyzed = sum(card.duration_s for card in cards)
    selected = [card for card in cards if card.outcome == "selected"]
    # The edit is as long as the windows that will be exported, not as long as the
    # segments they sit in; a segment with no window yet counts as its whole span.
    selected_seconds = sum(
        card.window_seconds if card.window_seconds is not None else card.duration_s
        for card in selected
    )
    return Summary(
        file_count=len(manifest.files),
        segment_count=len(cards),
        files_per_class=[(name, per_class[name]) for name in SOURCE_CLASSES if per_class[name]],
        segments_per_outcome=[
            (name, per_outcome[name])
            for name in ("candidate", "selected", "rejected")
            if per_outcome[name]
        ],
        segments_per_reason=[(name, per_reason[name]) for name in ALL_REASONS if per_reason[name]],
        analyzed_seconds=analyzed,
        analyzed_label=duration_label(analyzed),
        files_from_cache=manifest.analysis.files_from_cache,
        files_failed=manifest.analysis.files_failed,
        completed=manifest.analysis.completed,
        selected_count=len(selected),
        cluster_count=len({card.cluster_id for card in cards if card.cluster_id is not None}),
        diversity_lambda=manifest.selection.diversity_lambda,
        selected_seconds=selected_seconds,
        selected_label=duration_label(selected_seconds),
        exported_count=sum(1 for card in cards if card.exported_name),
        snapped_count=sum(1 for card in cards if card.snapped),
        places=build_places(manifest, cards),
        export_mode=manifest.export.mode,
        export_fps=manifest.export.target_fps,
        export_failed=manifest.export.failed,
        fps_converted_count=sum(1 for card in cards if card.fps_converted),
        classes=[name for name in SOURCE_CLASSES if per_class[name]],
        outcomes=[name for name in ("candidate", "selected", "rejected") if per_outcome[name]],
        reasons=[name for name in ALL_REASONS if per_reason[name]],
    )


def relative_asset(path: Path | None, out_dir: Path) -> str | None:
    """Address an asset from the report, so the whole output folder can be moved."""
    if path is None:
        return None
    try:
        return path.resolve().relative_to(out_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def timecode(seconds: float) -> str:
    """``m:ss.s``, the form the user reads back against the source clip."""
    seconds = max(seconds, 0.0)
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:04.1f}"


def duration_label(seconds: float) -> str:
    """A total, in the largest unit that still says something."""
    seconds = max(seconds, 0.0)
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)} min {int(rest)} s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours} h {minutes} min"


def _number(value: float | int | None) -> str:
    """Metric values span orders of magnitude, so significant digits beat fixed decimals.

    Values below one keep four decimals even when they are exactly zero, so the
    metric columns stay aligned down the grid.
    """
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.4f}"

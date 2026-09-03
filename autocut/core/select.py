"""Choose the final ordered set of clips.

Ranking by score alone over a holiday folder returns ten versions of the same
beach, so selection is greedy with a similarity penalty: at each step it takes the
candidate maximizing ``score - lambda * max similarity to what is already
selected``. Lambda is the diversity slider, and it is meant to be turned. The
whole point of the analysis cache is that this runs in seconds, so the tuning loop
is `select` twenty times over one `analyze`.

Everything here reads cached arrays. No video is decoded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from autocut.core.cache import CacheEntry, read_entry, thumb_index
from autocut.core.config import SOURCE_CLASSES, AutocutConfig, SourceClass
from autocut.core.durations import assign_durations, buckets, shortfall, total_duration
from autocut.core.manifest import Manifest, Segment, SelectionRun, SourceFile
from autocut.core.places import PlaceIndex, build_index, candidate_position
from autocut.core.rules import EXCLUSIONS
from autocut.core.similarity import (
    CandidateFeatures,
    SimilarityMatrix,
    assign_clusters,
    color_histogram,
    perceptual_hash,
)
from autocut.core.window import (
    ClassNorms,
    best_window,
    build_class_norms,
    frame_scores,
    snap_start,
)


@dataclass(slots=True)
class SelectionOverrides:
    """Command line values that win over configuration for one run."""

    max_clips: int | None = None
    target_duration_s: float | None = None
    diversity_lambda: float | None = None


@dataclass(slots=True)
class SelectionResult:
    """What one selection pass decided."""

    selected: list[str] = field(default_factory=list)
    clusters: int = 0
    max_clips: int = 0
    target_duration_s: float = 0.0
    diversity_lambda: float = 0.0
    relaxed_gap: bool = False
    total_duration_s: float = 0.0
    places: int = 0
    visits: int = 0
    held_by_place: int = 0
    ceiling_applied: bool = False
    varied_durations: bool = True
    long_clips: int = 0
    short_clips: int = 0
    hero_clips: int = 0
    total_shortfall_s: float = 0.0

    @property
    def count(self) -> int:
        return len(self.selected)


def select_clips(
    manifest: Manifest,
    config: AutocutConfig,
    overrides: SelectionOverrides | None = None,
) -> SelectionResult:
    """Reset the previous selection and choose again with the current settings."""
    overrides = overrides or SelectionOverrides()
    # "is not None" rather than "or": an explicit 0 is a value, not a missing option.
    max_clips = (
        overrides.max_clips if overrides.max_clips is not None else config.selection.max_clips
    )
    target = (
        overrides.target_duration_s
        if overrides.target_duration_s is not None
        else config.selection.target_duration_seconds
    )
    lam = (
        overrides.diversity_lambda
        if overrides.diversity_lambda is not None
        else config.selection.diversity_lambda
    )

    _reset(manifest)
    _mark_excluded(manifest, config)
    candidates = [s for s in manifest.segments.values() if s.outcome == "candidate"]
    eligible = [segment for segment in candidates if not _excluded(segment)]
    capped, ceiling_applied = _apply_share_ceiling(
        max_clips, len(eligible), config, explicit=overrides.max_clips is not None
    )
    result = SelectionResult(max_clips=capped, target_duration_s=target, diversity_lambda=lam)
    result.ceiling_applied = ceiling_applied
    max_clips = capped
    if not candidates:
        _record(manifest, result)
        return result

    entries = _load_entries(config, candidates)
    scores = _frame_scores(manifest, config, entries)
    # A first pass at the fallback length, because similarity and the temporal gap both
    # need a time for every candidate and the per-clip lengths are not known until the
    # picks are made. The selected clips get their windows placed again below.
    _place_windows(manifest, candidates, entries, scores, target)
    # Places need a window centre, because a drone's GPS tag is its takeoff point and
    # the telemetry fix that matters is the one under the shot.
    index = _assign_places(manifest, config, candidates, entries)
    result.places = index.place_count
    result.visits = index.visit_count
    features = _build_features(manifest, candidates, entries)
    matrix = SimilarityMatrix(features, config)

    ids = [segment.id for segment in candidates]
    clusters = assign_clusters(ids, matrix, config.selection.cluster_threshold)
    for segment in candidates:
        segment.cluster_id = clusters.get(segment.id)
    result.clusters = len(set(clusters.values()))

    chosen = _greedy(manifest, config, candidates, matrix, max_clips, lam, result)

    _finish(manifest, candidates, chosen, matrix, config)
    # Lengths need the final set: the hero share is a share of it and the alternation
    # pass walks it in order. Then the windows are searched again, each at the length
    # its clip was given, and nudged onto a motion boundary.
    assign_durations(chosen, manifest, config, overrides.target_duration_s)
    _place_windows(manifest, chosen, entries, scores, target, per_clip=True, config=config)
    result.held_by_place = sum(
        1
        for segment in candidates
        if segment.reason == "place_cap" and segment.outcome != "selected"
    )
    _record_durations(manifest, config, chosen, result)
    result.selected = [segment.id for segment in chosen]
    _record(manifest, result)
    return result


def _record_durations(
    manifest: Manifest,
    config: AutocutConfig,
    chosen: list[Segment],
    result: SelectionResult,
) -> None:
    """The rhythm of the edit, as numbers the CLI and the manifest can both print.

    Under ``--duration`` every clip is the same length, so the buckets describe
    nothing: they would still sort clips against their class base and still name the
    top scorers heroes, neither of which had any effect on a single duration.
    """
    result.total_duration_s = total_duration(chosen)
    result.total_shortfall_s = shortfall(chosen, config)
    result.varied_durations = not any(s.duration_reason == "override" for s in chosen)
    if not result.varied_durations:
        return
    counts = buckets(chosen, manifest, config)
    result.long_clips = counts["long"]
    result.short_clips = counts["short"]
    result.hero_clips = counts["hero"]


def _reset(manifest: Manifest) -> None:
    """Selections are disposable; rejections are not.

    A policy exclusion such as ``vertical`` is disposable too: it says what the
    current export strategy does with the clip, not that anything is wrong with it,
    so it is cleared and set again from the configuration this run was given.
    """
    for segment in manifest.segments.values():
        if segment.outcome == "selected":
            segment.outcome = "candidate"
        if segment.reason in EXCLUSIONS:
            segment.reason = None
        segment.order = None
        segment.lost_to = None
        segment.similarity_to_selected = None
        segment.cluster_id = None
        segment.place_id = None
        segment.visit_id = None
        segment.held_by = []


def _load_entries(config: AutocutConfig, candidates: list[Segment]) -> dict[str, CacheEntry]:
    entries: dict[str, CacheEntry] = {}
    for segment in candidates:
        if segment.file_id in entries:
            continue
        entry = read_entry(segment.file_id, config)
        if entry is not None:
            entries[segment.file_id] = entry
    return entries


def _class_of(manifest: Manifest, file_id: str) -> SourceClass:
    """The class a file was assigned at ingest; an unknown file is generic."""
    source = manifest.files.get(file_id)
    return source.source_class if source is not None else "generic"


def _frame_scores(
    manifest: Manifest, config: AutocutConfig, entries: dict[str, CacheEntry]
) -> dict[str, np.ndarray]:
    """One composite score per sampled frame, per file. Computed once for the run."""
    frames_by_class: dict[str, list[dict[str, np.ndarray]]] = {}
    for file_id, entry in entries.items():
        frames_by_class.setdefault(_class_of(manifest, file_id), []).append(entry.arrays)
    norms = build_class_norms(frames_by_class)
    return {
        file_id: frame_scores(
            entry.arrays,
            norms.get(_class_of(manifest, file_id), ClassNorms()),
            config.weights,
        )
        for file_id, entry in entries.items()
    }


def _place_windows(
    manifest: Manifest,
    segments: list[Segment],
    entries: dict[str, CacheEntry],
    scores: dict[str, np.ndarray],
    target: float,
    *,
    per_clip: bool = False,
    config: AutocutConfig | None = None,
) -> None:
    """Store where the good part of each segment is (ADR 5).

    ``per_clip`` searches at each segment's own assigned duration and, when the
    configuration asks for it, nudges the window start onto a motion minimum so the
    cut lands where movement begins rather than partway through it.
    """
    for segment in segments:
        cached = entries.get(segment.file_id)
        bounds = _bounds(segment)
        wanted = (segment.target_duration_s or target) if per_clip else target
        if cached is None:
            segment.best_center_s = (bounds[0] + bounds[1]) / 2.0
            segment.target_duration_s = min(wanted, bounds[1] - bounds[0])
            continue
        timestamps = cached.arrays.get("timestamps", np.zeros(0))
        center, duration = best_window(scores[segment.file_id], timestamps, bounds, wanted)
        segment.best_center_s = center
        segment.target_duration_s = duration
        if per_clip and config is not None and config.selection.snap_to_motion:
            start, snapped = snap_start(
                center - duration / 2.0,
                duration,
                scores[segment.file_id],
                timestamps,
                cached.arrays.get("motion", np.zeros(0)),
                bounds,
                config.selection.snap_window_seconds,
                config.selection.snap_max_score_loss,
            )
            segment.best_center_s = start + duration / 2.0
            segment.snapped = snapped


def _bounds(segment: Segment) -> tuple[float, float]:
    start = segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
    stop = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
    return start, stop


def _build_features(
    manifest: Manifest, candidates: list[Segment], entries: dict[str, CacheEntry]
) -> dict[str, CandidateFeatures]:
    features: dict[str, CandidateFeatures] = {}
    for segment in candidates:
        source = manifest.files.get(segment.file_id)
        entry = entries.get(segment.file_id)
        frame = _thumb_frame(segment, entry)
        features[segment.id] = CandidateFeatures(
            segment_id=segment.id,
            source_class=_class_of(manifest, segment.file_id),
            phash=perceptual_hash(frame) if frame is not None else None,
            histogram=color_histogram(frame) if frame is not None else None,
            embedding=_embedding(segment, entry),
            lat=source.gps.lat if source is not None and source.gps is not None else None,
            lon=source.gps.lon if source is not None and source.gps is not None else None,
            timestamp=absolute_time(source, segment),
            motion=_window_motion(segment, entry),
        )
    return features


def _thumb_frame(segment: Segment, entry: CacheEntry | None) -> np.ndarray | None:
    if entry is None or entry.thumb_frames is None or entry.thumb_frames.size == 0:
        return None
    index = thumb_index(segment.id, int(entry.thumb_frames.shape[0]))
    if index < 0:
        return None
    frame: np.ndarray = entry.thumb_frames[index]
    return frame


def _embedding(segment: Segment, entry: CacheEntry | None) -> np.ndarray | None:
    """The segment's vector, or ``None`` when this project has no embeddings.

    Indexed exactly like the thumbnail frame, because the vector describes that frame.
    A cache entry embedded with another model arrives here already emptied.
    """
    if entry is None or entry.embeddings is None or entry.embeddings.size == 0:
        return None
    index = thumb_index(segment.id, int(entry.embeddings.shape[0]))
    if index < 0:
        return None
    vector: np.ndarray = entry.embeddings[index]
    return vector


def _window_motion(segment: Segment, entry: CacheEntry | None) -> np.ndarray:
    if entry is None or segment.best_center_s is None:
        return np.zeros(0)
    timestamps = entry.arrays.get("timestamps")
    motion = entry.arrays.get("motion")
    if timestamps is None or motion is None or timestamps.size != motion.size:
        return np.zeros(0)
    half = (segment.target_duration_s or 0.0) / 2.0
    start, stop = segment.best_center_s - half, segment.best_center_s + half
    inside = np.flatnonzero((timestamps >= start) & (timestamps < stop))
    return motion[inside] if inside.size else np.zeros(0)


def absolute_time(source: SourceFile | None, segment: Segment) -> datetime | None:
    """When this clip happened: the file's creation time plus the window offset."""
    if source is None or source.creation_time is None:
        return None
    created = source.creation_time
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    offset = segment.best_center_s or 0.0
    return created + timedelta(seconds=offset)


def _greedy(
    manifest: Manifest,
    config: AutocutConfig,
    candidates: list[Segment],
    matrix: SimilarityMatrix,
    max_clips: int,
    lam: float,
    result: SelectionResult,
) -> list[Segment]:
    """Class shares first, then the open field, both by penalized score."""
    chosen: list[Segment] = []
    remaining = list(candidates)

    for source_class, quota in _class_quotas(manifest, config, candidates, max_clips).items():
        while (
            len(chosen) < max_clips
            and sum(1 for s in chosen if _class_of(manifest, s.file_id) == source_class) < quota
        ):
            pick = _best_pick(
                manifest,
                config,
                [s for s in remaining if _class_of(manifest, s.file_id) == source_class],
                chosen,
                matrix,
                lam,
                result,
            )
            if pick is None:
                break
            chosen.append(pick)
            remaining.remove(pick)

    while len(chosen) < max_clips:
        pick = _best_pick(manifest, config, remaining, chosen, matrix, lam, result)
        if pick is None:
            break
        chosen.append(pick)
        remaining.remove(pick)
    return chosen


def _class_quotas(
    manifest: Manifest, config: AutocutConfig, candidates: list[Segment], max_clips: int
) -> dict[SourceClass, int]:
    """Slots reserved before the open field, so a minority class is not crowded out.

    The share is a floor on the final count, so it rounds up: a fifth of nine clips
    is two clips, not one. Reservations are capped at ``max_clips`` in total, because
    several generous shares can otherwise ask for more slots than the edit has.
    """
    quotas: dict[SourceClass, int] = {}
    reserved = 0
    for source_class in SOURCE_CLASSES:
        share = config.selection.min_share_per_class.get(source_class)
        if share <= 0:
            continue
        wanted = math.ceil(share * max_clips)
        available = sum(1 for s in candidates if _class_of(manifest, s.file_id) == source_class)
        # A share that asks for more clips than the class has takes what there is.
        quota = min(wanted, available, max_clips - reserved)
        if quota > 0:
            quotas[source_class] = quota
            reserved += quota
    return quotas


def _best_pick(
    manifest: Manifest,
    config: AutocutConfig,
    pool: list[Segment],
    chosen: list[Segment],
    matrix: SimilarityMatrix,
    lam: float,
    result: SelectionResult,
) -> Segment | None:
    """The eligible candidate with the highest penalized score.

    Two passes. The first honours every cap; the second lifts the two that exist to
    spread the edit out, the minimum temporal gap and the place cap, because an edit
    short of clips is worse than an edit with two shots from one spot.
    """
    chosen_ids = [segment.id for segment in chosen]
    taken = set(chosen_ids)
    for relaxed in (False, True):
        eligible = [
            segment
            for segment in pool
            if segment.id not in taken
            and _eligible(manifest, config, segment, chosen, relaxed=relaxed)
        ]
        if not eligible:
            continue
        best: Segment | None = None
        best_value = -np.inf
        for segment in eligible:
            penalty, _ = matrix.max_against(segment.id, chosen_ids)
            value = (segment.score or 0.0) - lam * penalty
            if value > best_value:
                best_value, best = value, segment
        if relaxed:
            result.relaxed_gap = True
        return best
    return None


def _apply_share_ceiling(
    max_clips: int, eligible: int, config: AutocutConfig, *, explicit: bool
) -> tuple[int, bool]:
    """Bound ``max_clips`` to a share of the eligible candidates, unless asked otherwise.

    Forty slots for sixty candidates is not a selection, it is a rejection list: the
    diversity penalty can only reorder what it is forced to take anyway. Tying the
    slot count to the folder makes a small shoot produce a short edit without the user
    having to work out the number, and a large one still hits ``max_clips`` first.

    An explicit ``--max-clips`` is the user overruling exactly this, so it wins.
    """
    share = config.selection.max_candidate_share
    if explicit or share <= 0 or eligible <= 0:
        return max_clips, False
    ceiling = math.ceil(share * eligible)
    if ceiling >= max_clips:
        return max_clips, False
    return ceiling, True


def _assign_places(
    manifest: Manifest,
    config: AutocutConfig,
    candidates: list[Segment],
    entries: dict[str, CacheEntry],
) -> PlaceIndex:
    """Group the candidates by where and when they were shot, and record it on each."""
    positions = {}
    order: dict[str, datetime | None] = {}
    for segment in candidates:
        source = manifest.files.get(segment.file_id)
        entry = entries.get(segment.file_id)
        position = candidate_position(segment, source, entry.telemetry if entry else None)
        if position is not None:
            positions[segment.id] = position
        order[segment.id] = absolute_time(source, segment)

    index = build_index(
        positions,
        order,
        config.selection.place_radius_m,
        config.selection.place_visit_gap_seconds,
    )
    for segment in candidates:
        segment.place_id = index.place_of.get(segment.id)
        segment.visit_id = index.visit_of.get(segment.id)
    return index


def _mark_excluded(manifest: Manifest, config: AutocutConfig) -> None:
    """Record which candidates a policy holds back, before anything competes.

    A vertical clip under the ``exclude`` strategy cannot be exported, so selecting
    it would put a hole in the edit. It stays a candidate with reason ``vertical``:
    the user chose this, and silently dropping the clip is the kind of decision that
    is only discovered in CapCut.
    """
    if config.export.vertical_strategy != "exclude":
        return
    for segment in manifest.segments.values():
        if segment.outcome != "candidate":
            continue
        source = manifest.files.get(segment.file_id)
        if source is not None and source.is_vertical:
            segment.reason = "vertical"


def _excluded(segment: Segment) -> bool:
    return segment.reason in EXCLUSIONS


def _eligible(
    manifest: Manifest,
    config: AutocutConfig,
    segment: Segment,
    chosen: list[Segment],
    *,
    relaxed: bool,
) -> bool:
    if segment.outcome != "candidate" or _excluded(segment):
        return False

    source_class = _class_of(manifest, segment.file_id)
    per_file = config.selection.max_clips_per_file.get(source_class)
    if sum(1 for s in chosen if s.file_id == segment.file_id) >= per_file:
        return False

    if segment.cluster_id is not None:
        same_cluster = sum(1 for s in chosen if s.cluster_id == segment.cluster_id)
        if same_cluster >= config.selection.max_clips_per_cluster:
            return False

    if relaxed:
        return True

    # One spot on one outing gives a few clips, however different the pixels look.
    # A candidate with no GPS has no visit and is never held back by this.
    if segment.visit_id is not None:
        same_visit = sum(1 for s in chosen if s.visit_id == segment.visit_id)
        if same_visit >= config.selection.max_clips_per_place:
            return False

    gap = config.selection.min_temporal_gap_seconds
    if gap <= 0:
        return True
    when = absolute_time(manifest.files.get(segment.file_id), segment)
    if when is None:
        return True
    for other in chosen:
        other_when = absolute_time(manifest.files.get(other.file_id), other)
        if other_when is None:
            continue
        if abs((when - other_when).total_seconds()) < gap:
            return False
    return True


def _finish(
    manifest: Manifest,
    candidates: list[Segment],
    chosen: list[Segment],
    matrix: SimilarityMatrix,
    config: AutocutConfig,
) -> None:
    """Mark the picks, order them by absolute time, and say why the others lost."""
    chosen_ids = [segment.id for segment in chosen]
    for segment in chosen:
        segment.outcome = "selected"

    def when(segment: Segment) -> tuple[datetime, str]:
        moment = absolute_time(manifest.files.get(segment.file_id), segment)
        return moment or datetime.fromtimestamp(0, tz=UTC), segment.id

    for order, segment in enumerate(sorted(chosen, key=when), start=1):
        segment.order = order

    filled = _filled_visits(chosen, config)
    for segment in candidates:
        if segment.outcome == "selected":
            continue
        similarity, winner = matrix.max_against(segment.id, chosen_ids)
        segment.similarity_to_selected = similarity
        if winner is not None and similarity >= config.selection.cluster_threshold:
            segment.lost_to = winner
        holders = filled.get(segment.visit_id) if segment.visit_id is not None else None
        if holders:
            # The cap is why this one is not in the edit, whatever else is also true
            # of it, and the card should name the three clips that took the slots.
            segment.reason = "place_cap"
            segment.held_by = holders


def _filled_visits(chosen: list[Segment], config: AutocutConfig) -> dict[int, list[str]]:
    """For each visit the cap actually bound, the ids of the clips that filled it.

    A visit holding more than the cap is one where the cap was lifted, because
    nothing outside it was eligible and slots remained. Nothing in such a visit was
    held back by the cap: the candidates that missed out lost on score like any
    other, and saying otherwise would put the wrong word on their card.
    """
    by_visit: dict[int, list[str]] = {}
    for segment in sorted(chosen, key=lambda s: (s.order if s.order is not None else 0, s.id)):
        if segment.visit_id is not None:
            by_visit.setdefault(segment.visit_id, []).append(segment.id)
    cap = config.selection.max_clips_per_place
    return {visit: ids for visit, ids in by_visit.items() if len(ids) == cap}


def _record(manifest: Manifest, result: SelectionResult) -> None:
    manifest.selection = SelectionRun(
        ran_at=datetime.now(UTC),
        diversity_lambda=result.diversity_lambda,
        max_clips=result.max_clips,
        target_duration_s=result.target_duration_s,
        places=result.places,
        visits=result.visits,
        total_duration_s=round(result.total_duration_s, 3),
        selected=result.count,
        clusters=result.clusters,
    )

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

from autocut.core.cache import CacheEntry, read_entry
from autocut.core.config import SOURCE_CLASSES, AutocutConfig, SourceClass
from autocut.core.manifest import Manifest, Segment, SelectionRun, SourceFile
from autocut.core.similarity import (
    CandidateFeatures,
    SimilarityMatrix,
    assign_clusters,
    color_histogram,
    perceptual_hash,
)
from autocut.core.window import ClassNorms, best_window, build_class_norms, frame_scores


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
    candidates = [s for s in manifest.segments.values() if s.outcome == "candidate"]
    result = SelectionResult(max_clips=max_clips, target_duration_s=target, diversity_lambda=lam)
    if not candidates:
        _record(manifest, result)
        return result

    entries = _load_entries(config, candidates)
    _place_windows(manifest, config, candidates, entries, target)
    features = _build_features(manifest, candidates, entries)
    matrix = SimilarityMatrix(features, config)

    ids = [segment.id for segment in candidates]
    clusters = assign_clusters(ids, matrix, config.selection.cluster_threshold)
    for segment in candidates:
        segment.cluster_id = clusters.get(segment.id)
    result.clusters = len(set(clusters.values()))

    chosen = _greedy(manifest, config, candidates, matrix, max_clips, lam, result)

    _finish(manifest, candidates, chosen, matrix, config)
    result.selected = [segment.id for segment in chosen]
    _record(manifest, result)
    return result


def _reset(manifest: Manifest) -> None:
    """Selections are disposable; rejections are not."""
    for segment in manifest.segments.values():
        if segment.outcome == "selected":
            segment.outcome = "candidate"
        segment.order = None
        segment.lost_to = None
        segment.similarity_to_selected = None
        segment.cluster_id = None


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


def _place_windows(
    manifest: Manifest,
    config: AutocutConfig,
    candidates: list[Segment],
    entries: dict[str, CacheEntry],
    target: float,
) -> None:
    """Store where the good part of each candidate is (ADR 5)."""
    frames_by_class: dict[str, list[dict[str, np.ndarray]]] = {}
    for file_id, entry in entries.items():
        frames_by_class.setdefault(_class_of(manifest, file_id), []).append(entry.arrays)
    norms = build_class_norms(frames_by_class)

    scores_by_file: dict[str, np.ndarray] = {}
    for file_id, entry in entries.items():
        scores_by_file[file_id] = frame_scores(
            entry.arrays,
            norms.get(_class_of(manifest, file_id), ClassNorms()),
            config.weights,
        )

    for segment in candidates:
        cached = entries.get(segment.file_id)
        bounds = _bounds(segment)
        if cached is None:
            segment.best_center_s = (bounds[0] + bounds[1]) / 2.0
            segment.target_duration_s = min(target, bounds[1] - bounds[0])
            continue
        center, duration = best_window(
            scores_by_file[segment.file_id],
            cached.arrays.get("timestamps", np.zeros(0)),
            bounds,
            target,
        )
        segment.best_center_s = center
        segment.target_duration_s = duration


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
            lat=source.gps.lat if source is not None and source.gps is not None else None,
            lon=source.gps.lon if source is not None and source.gps is not None else None,
            timestamp=absolute_time(source, segment),
            motion=_window_motion(segment, entry),
        )
    return features


def _thumb_frame(segment: Segment, entry: CacheEntry | None) -> np.ndarray | None:
    if entry is None or entry.thumb_frames is None or entry.thumb_frames.size == 0:
        return None
    index = _shot_index(segment)
    if index >= entry.thumb_frames.shape[0]:
        index = entry.thumb_frames.shape[0] - 1
    frame: np.ndarray = entry.thumb_frames[index]
    return frame


def _shot_index(segment: Segment) -> int:
    _, _, suffix = segment.id.rpartition(":")
    try:
        return max(int(suffix), 0)
    except ValueError:
        return 0


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
    """The eligible candidate with the highest penalized score, gap relaxed as a last resort."""
    chosen_ids = [segment.id for segment in chosen]
    taken = set(chosen_ids)
    for relax_gap in (False, True):
        eligible = [
            segment
            for segment in pool
            if segment.id not in taken
            and _eligible(manifest, config, segment, chosen, relax_gap=relax_gap)
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
        if relax_gap:
            result.relaxed_gap = True
        return best
    return None


def _eligible(
    manifest: Manifest,
    config: AutocutConfig,
    segment: Segment,
    chosen: list[Segment],
    *,
    relax_gap: bool,
) -> bool:
    if segment.outcome != "candidate":
        return False

    source_class = _class_of(manifest, segment.file_id)
    per_file = config.selection.max_clips_per_file.get(source_class)
    if sum(1 for s in chosen if s.file_id == segment.file_id) >= per_file:
        return False

    if segment.cluster_id is not None:
        same_cluster = sum(1 for s in chosen if s.cluster_id == segment.cluster_id)
        if same_cluster >= config.selection.max_clips_per_cluster:
            return False

    if relax_gap:
        return True
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

    for segment in candidates:
        if segment.outcome == "selected":
            continue
        similarity, winner = matrix.max_against(segment.id, chosen_ids)
        segment.similarity_to_selected = similarity
        if winner is not None and similarity >= config.selection.cluster_threshold:
            segment.lost_to = winner


def _record(manifest: Manifest, result: SelectionResult) -> None:
    manifest.selection = SelectionRun(
        ran_at=datetime.now(UTC),
        diversity_lambda=result.diversity_lambda,
        max_clips=result.max_clips,
        target_duration_s=result.target_duration_s,
        selected=result.count,
        clusters=result.clusters,
    )

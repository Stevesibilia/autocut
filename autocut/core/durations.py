"""Give each selected clip its own length.

Forty clips of exactly three seconds read as a slideshow. An aerial needs longer
to be taken in, an action shot feels long at three seconds, the best shots earn
room to breathe, and an edit that never varies its shot length never accelerates
or settles. Editors do this by hand; everything needed to do it here is already
in the manifest, so it costs milliseconds and happens before any music exists.

The order is fixed and each step is one idea: a base per class, scaled by the
clip's score, a bonus for the best few, then a pass that breaks up runs of the
same length, then an optional scale onto a total, and clamps throughout. Every
clip ends up with one word saying which rule settled its length, because a
duration nobody can explain is a duration nobody can tune.

Milestone M4 reads the assigned durations and rounds them to beat multiples. It
does not re-derive them from the score, which is why the reason is recorded: a
hero clip keeps the longer multiple when a rounding lands on a tie.
"""

from __future__ import annotations

from autocut.core.config import AutocutConfig, SourceClass
from autocut.core.manifest import DurationReason, Manifest, Segment

# A clip is "long" when it is at or above its class base and "short" below it.
# Comparing against the class base rather than an absolute number is what lets a
# 2.0 s action clip and a 4.0 s drone clip both count as ordinary.
LONG = "long"
SHORT = "short"


def trimmed_span(segment: Segment) -> float:
    start = segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
    stop = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
    return max(stop - start, 0.0)


def class_of(manifest: Manifest, segment: Segment) -> SourceClass:
    source = manifest.files.get(segment.file_id)
    return source.source_class if source is not None else "generic"


def base_duration(manifest: Manifest, segment: Segment, config: AutocutConfig) -> float:
    """The class's base length, or the project fallback when the class has none."""
    base = config.selection.duration_by_class.get(class_of(manifest, segment))
    return base if base > 0 else config.selection.target_duration_seconds


def score_factor(score: float | None, config: AutocutConfig) -> float:
    """Where this clip's score puts it between the two ends of the range."""
    low, high = config.selection.score_duration_range
    return low + (high - low) * min(max(score or 0.0, 0.0), 1.0)


def clamp(duration: float, segment: Segment, config: AutocutConfig) -> tuple[float, bool]:
    """Bound a duration, and say whether the segment's own span was what bound it.

    The configured minimum and maximum are settings, and a clip sitting on one is
    unremarkable. A clip cut short because the shot itself is shorter than the
    length the rules asked for is worth a word in the report, so only that case
    reports back as clamped.
    """
    bounded = min(
        max(duration, config.selection.duration_min_seconds), config.selection.duration_max_seconds
    )
    span = trimmed_span(segment)
    if span > 0 and span < bounded:
        return span, True
    return bounded, False


def bucket(duration: float, base: float) -> str:
    return LONG if duration >= base else SHORT


def assign_durations(
    selected: list[Segment],
    manifest: Manifest,
    config: AutocutConfig,
    override: float | None = None,
) -> None:
    """Write ``target_duration_s`` and ``duration_reason`` on every selected clip.

    ``override`` is the ``--duration`` flag: one length for every clip, no scaling,
    no heroes and no alternation, which is the milestone 2 behaviour kept reachable.
    """
    if not selected:
        manifest.selection.total_duration_s = 0.0
        return

    if override is not None:
        for segment in selected:
            span = trimmed_span(segment)
            # Bounded by the shot and by nothing else. The flag exists to ask for one
            # length everywhere, so the configured minimum and maximum stay out of it.
            segment.target_duration_s = min(override, span) if span > 0 else override
            segment.duration_reason = "override"
        _record_total(manifest, selected)
        return

    reasons: dict[str, DurationReason] = {}
    bases: dict[str, float] = {}
    for segment in selected:
        base = base_duration(manifest, segment, config)
        bases[segment.id] = base
        segment.target_duration_s = base * score_factor(segment.score, config)
        reasons[segment.id] = "base"

    _apply_heroes(selected, config, reasons)
    _clamp_all(selected, config, reasons)

    if config.selection.alternate_durations:
        _alternate(selected, config, bases, reasons)
    if config.selection.target_total_seconds:
        _scale_to_total(selected, config, reasons)

    for segment in selected:
        segment.duration_reason = reasons[segment.id]
    _record_total(manifest, selected)


def heroes(selected: list[Segment], config: AutocutConfig) -> set[str]:
    """The ids of the top share by score. A share too small for one clip picks none."""
    count = int(config.selection.hero_share * len(selected))
    if count <= 0:
        return set()
    ranked = sorted(selected, key=lambda s: (-(s.score or 0.0), s.id))
    return {segment.id for segment in ranked[:count]}


def _apply_heroes(
    selected: list[Segment], config: AutocutConfig, reasons: dict[str, DurationReason]
) -> None:
    """The best few get room to breathe. Applied before clamping, as the spec states."""
    chosen = heroes(selected, config)
    for segment in selected:
        if segment.id in chosen and segment.target_duration_s is not None:
            segment.target_duration_s *= config.selection.hero_multiplier
            reasons[segment.id] = "hero"


def _clamp_all(
    selected: list[Segment], config: AutocutConfig, reasons: dict[str, DurationReason]
) -> None:
    for segment in selected:
        duration, by_span = clamp(segment.target_duration_s or 0.0, segment, config)
        segment.target_duration_s = duration
        if by_span:
            reasons[segment.id] = "clamped"


def _alternate(
    selected: list[Segment],
    config: AutocutConfig,
    bases: dict[str, float],
    reasons: dict[str, DurationReason],
) -> None:
    """Break every run of three clips in the same bucket, in chronological order.

    One left to right pass, not iterated. Each adjustment is visible to the window
    that follows it, so a run of five is broken twice, but nothing is revisited: a
    rule that keeps re-deciding is a rule nobody can predict from the report.
    """
    order = sorted(selected, key=lambda s: (s.order if s.order is not None else 0, s.id))
    hero_ids = heroes(selected, config)

    for index in range(len(order) - 2):
        window = order[index : index + 3]
        run = {bucket(s.target_duration_s or 0.0, bases[s.id]) for s in window}
        if len(run) != 1:
            continue
        shortening = run == {LONG}
        # A hero earned its length; the run is broken with the next clip instead.
        target = window[1]
        if shortening and target.id in hero_ids:
            target = window[2]
            if target.id in hero_ids:
                continue
        _move_bucket(target, config, reasons, shorten=shortening)


def _move_bucket(
    segment: Segment,
    config: AutocutConfig,
    reasons: dict[str, DurationReason],
    *,
    shorten: bool,
) -> None:
    """Scale one clip a quarter towards the other bucket, within its bounds."""
    before = segment.target_duration_s or 0.0
    scaled = before * (0.75 if shorten else 1.25)
    duration, by_span = clamp(scaled, segment, config)
    segment.target_duration_s = duration
    if duration == before:
        # The clamps left it where it was, so nothing about it changed to report.
        return
    reasons[segment.id] = "clamped" if by_span else "alternation"


def _scale_to_total(
    selected: list[Segment], config: AutocutConfig, reasons: dict[str, DurationReason]
) -> None:
    """One factor for every clip, so the relative rhythm survives the resize."""
    target_total = config.selection.target_total_seconds
    current = sum(segment.target_duration_s or 0.0 for segment in selected)
    if not target_total or current <= 0:
        return
    factor = target_total / current
    for segment in selected:
        before = segment.target_duration_s or 0.0
        duration, by_span = clamp(before * factor, segment, config)
        segment.target_duration_s = duration
        if duration == before:
            continue
        reasons[segment.id] = "clamped" if by_span else "total"


def total_duration(selected: list[Segment]) -> float:
    return sum(segment.target_duration_s or 0.0 for segment in selected)


def shortfall(selected: list[Segment], config: AutocutConfig) -> float:
    """How far the edit lands from a requested total, positive when it is short.

    Clamps can leave the target out of reach. That is reported rather than fixed by
    dropping clips, because how many clips the edit holds is the user's `max_clips`
    decision and not this module's to revisit.
    """
    target_total = config.selection.target_total_seconds
    if not target_total:
        return 0.0
    return target_total - total_duration(selected)


def buckets(selected: list[Segment], manifest: Manifest, config: AutocutConfig) -> dict[str, int]:
    """How many clips are long, short and hero, for the summary line."""
    hero_ids = heroes(selected, config)
    counts = {LONG: 0, SHORT: 0, "hero": len(hero_ids)}
    for segment in selected:
        base = base_duration(manifest, segment, config)
        counts[bucket(segment.target_duration_s or 0.0, base)] += 1
    return counts


def _record_total(manifest: Manifest, selected: list[Segment]) -> None:
    manifest.selection.total_duration_s = round(total_duration(selected), 3)

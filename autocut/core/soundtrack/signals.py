"""What the edit is, as the numbers and words a prompt can be written from.

Nothing here reads a file or a frame. Everything comes off the manifest, which by this
point knows the durations the clips were given, the energy in them, what they show, the
places they were shot at and when. That matters twice over: the prompt is derived from
the edit rather than from the footage, and the refinement step has something to send to
a hosted model that is not the footage.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from autocut.core.config import AutocutConfig, TimeOfDayBands
from autocut.core.manifest import Manifest, Segment, SoundtrackSignals
from autocut.core.select import absolute_time

#: Clips either side of a clip are averaged into it. Three is enough to stop one shaky
#: shot reading as a peak and short enough to keep a real build visible.
SMOOTHING_WINDOW = 3

MAX_CAPTIONS = 5
MAX_PLACE_NAMES = 3


def selected_in_order(manifest: Manifest) -> list[Segment]:
    """The edit, in the order it will be exported."""
    chosen = [s for s in manifest.segments.values() if s.outcome == "selected"]
    return sorted(chosen, key=lambda s: (s.order if s.order is not None else 0, s.id))


def energy_curve(segments: list[Segment], window: int = SMOOTHING_WINDOW) -> list[float]:
    """One value per clip in 0 to 1, smoothed, from the motion in each clip.

    Ranked rather than scaled, for the reason scoring ranks: raw motion is not
    comparable between a drone cruising and an action cam on a wrist, and one outlier
    would otherwise flatten everything else into the same band.
    """
    if not segments:
        return []
    motion = np.array(
        [s.metrics.motion if s.metrics is not None else 0.0 for s in segments], dtype=np.float64
    )
    if motion.size == 1:
        return [0.5]
    order = np.argsort(motion, kind="stable")
    ranks = np.empty(motion.size, dtype=np.float64)
    ranks[order] = np.arange(motion.size, dtype=np.float64)
    normalized = ranks / (motion.size - 1)
    if window > 1:
        kernel = np.ones(min(window, motion.size)) / min(window, motion.size)
        normalized = np.convolve(normalized, kernel, mode="same")
        # Convolving with "same" divides the ends by the full window even though fewer
        # values landed there, which drags the first and last clip toward zero.
        edge = min(window, motion.size) // 2
        for index in range(edge):
            normalized[index] = float(np.mean(normalized[: index + edge + 1]))
            normalized[-(index + 1)] = float(np.mean(normalized[-(index + edge + 1) :]))
    return [float(np.clip(value, 0.0, 1.0)) for value in normalized]


def band_of(value: float, bands: tuple[float, float]) -> str:
    """Which of low, mid or high a normalized energy falls in."""
    low, high = bands
    if value < low:
        return "low"
    return "high" if value >= high else "mid"


def peak_third(curve: list[float]) -> int:
    """Which third of the edit carries the most energy, 0, 1 or 2.

    The structure arc puts its peak here, so a build that actually happens late in the
    edit is not written as a generic middle climax.
    """
    if not curve:
        return 1
    thirds = np.array_split(np.array(curve, dtype=np.float64), 3)
    means = [float(part.mean()) if part.size else 0.0 for part in thirds]
    return int(np.argmax(means))


def time_of_day(segments: list[Segment], manifest: Manifest, config: AutocutConfig) -> str:
    """The band most of the clips were shot in, by local hour."""
    bands = config.soundtrack.time_of_day
    counts: Counter[str] = Counter()
    for segment in segments:
        when = absolute_time(manifest.files.get(segment.file_id), segment)
        if when is None:
            continue
        hour = when.astimezone().hour
        counts[_band_for_hour(hour, bands)] += 1
    if not counts:
        return "daytime"
    return counts.most_common(1)[0][0]


def _band_for_hour(hour: int, bands: TimeOfDayBands) -> str:
    for name in ("morning", "daytime", "evening"):
        start, end = getattr(bands, name)
        if start <= hour < end:
            return name
    return "night"


def derive_signals(manifest: Manifest, config: AutocutConfig) -> SoundtrackSignals:
    """Everything the prompt is written from, in one record on the manifest."""
    segments = selected_in_order(manifest)
    curve = energy_curve(segments)
    # Two counts, because two questions are asked of them. "Which tag names this edit"
    # is about the dominant tags only; "is underwater anywhere in it" is about every tag
    # a clip carries, and a view tag such as underwater is never dominant by design.
    dominant_counts = Counter(
        segment.dominant_tag for segment in segments if segment.dominant_tag is not None
    )
    tags: Counter[str] = Counter()
    for segment in segments:
        for label in {tag.label for tag in segment.tags}:
            tags[label] += 1
    classes = Counter(
        manifest.files[segment.file_id].source_class
        for segment in segments
        if segment.file_id in manifest.files
    )
    total = float(sum(segment.target_duration_s or 0.0 for segment in segments))
    count = len(segments)
    dominant, dominant_count = dominant_counts.most_common(1)[0] if dominant_counts else (None, 0)
    mean_energy = float(np.mean(curve)) if curve else 0.5
    named = [
        place.name
        for place in sorted(manifest.places.values(), key=lambda p: -p.segments)
        if place.name
    ]
    regions = [place.region for place in manifest.places.values() if place.region]
    return SoundtrackSignals(
        total_duration_s=round(total, 1),
        clip_count=count,
        energy_curve=[round(value, 3) for value in curve],
        energy_band=band_of(mean_energy, config.soundtrack.energy_bands),
        peak_third=peak_third(curve),
        dominant_tag=dominant,
        dominant_tag_share=round(dominant_count / count, 3) if count else 0.0,
        # Every tag on the edit with how many clips carry it, most carried first.
        tags=dict(tags.most_common()),
        captions=[s.caption for s in segments if s.caption][:MAX_CAPTIONS],
        class_mix={name: round(number / count, 3) for name, number in classes.most_common()}
        if count
        else {},
        time_of_day=time_of_day(segments, manifest, config),
        place_names=named[:MAX_PLACE_NAMES],
        regions=sorted(set(regions)),
    )


def clip_durations(manifest: Manifest) -> list[float]:
    """The lengths the edit will actually use, which is what the BPM is fitted to."""
    return [
        segment.target_duration_s
        for segment in selected_in_order(manifest)
        if segment.target_duration_s
    ]

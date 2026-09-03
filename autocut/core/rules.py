"""Deterministic rejection rules, applied before scoring.

A rejected segment keeps its metrics and stays in the manifest so the report can
show why it went and the user can disagree. Rules are evaluated in a fixed order
and the first one that fires wins, so the recorded reason is stable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autocut.core.config import AutocutConfig
from autocut.core.manifest import Metrics, Segment

if TYPE_CHECKING:
    from autocut.core.telemetry import TelemetrySample

REASONS = ("too_short", "low_altitude", "no_motion", "shaky", "clipped")


def segment_heights(segment: Segment, telemetry: list[TelemetrySample] | None) -> list[float]:
    """Heights recorded inside the segment's trimmed span.

    The window is half open. Altitude splits put a boundary exactly on a telemetry
    timestamp, and that sample describes the span that starts there, not the one
    that ends there. Counting it twice would let the first sample of the cruise
    rescue the takeoff span it was split away from.
    """
    if not telemetry:
        return []
    start = segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
    stop = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
    return [
        sample.height_m
        for sample in telemetry
        if sample.height_m is not None and start <= sample.time_s < stop
    ]


def apply_rules(
    segment: Segment,
    metrics: Metrics,
    telemetry: list[TelemetrySample] | None,
    config: AutocutConfig,
) -> str | None:
    """The reason this segment is unusable, or ``None`` when it survives."""
    start = segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
    stop = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
    if stop - start < config.selection.min_segment_seconds:
        return "too_short"

    heights = segment_heights(segment, telemetry)
    if heights and max(heights) < config.rules.drone.min_height_m:
        return "low_altitude"

    if metrics.motion < config.rules.min_motion:
        return "no_motion"

    if metrics.motion > config.rules.max_motion and metrics.stability < config.rules.min_stability:
        return "shaky"

    if metrics.exposure_clipped > config.rules.max_clipped_fraction:
        return "clipped"

    return None

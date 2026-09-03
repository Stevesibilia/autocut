"""Every scenario in specs/rejection-rules."""

from __future__ import annotations

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.manifest import Metrics, Segment
from autocut.core.rules import REASONS, apply_rules
from autocut.core.telemetry import TelemetrySample


def segment(start: float = 0.0, stop: float = 4.0) -> Segment:
    return Segment(
        id="f:0",
        file_id="f",
        start_s=start,
        end_s=stop,
        trimmed_start_s=start,
        trimmed_end_s=stop,
    )


def metrics(
    motion: float = 0.3,
    stability: float = 0.9,
    clipped: float = 0.0,
    sharpness: float = 100.0,
) -> Metrics:
    return Metrics(
        sharpness=sharpness,
        exposure_clipped=clipped,
        motion=motion,
        stability=stability,
        colorfulness=0.2,
    )


def heights(*pairs: tuple[float, float]) -> list[TelemetrySample]:
    return [TelemetrySample(time_s=time, height_m=height) for time, height in pairs]


def test_a_healthy_segment_survives() -> None:
    assert apply_rules(segment(), metrics(), None, AutocutConfig()) is None


def test_short_segment() -> None:
    config = AutocutConfig()
    assert config.selection.min_segment_seconds == pytest.approx(1.5)
    assert apply_rules(segment(0.0, 1.0), metrics(), None, config) == "too_short"


def test_takeoff_segment_is_low_altitude() -> None:
    config = AutocutConfig()
    assert config.rules.drone.min_height_m == pytest.approx(5.0)
    telemetry = heights((0.0, 0.5), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0))
    assert apply_rules(segment(0.0, 3.0), metrics(), telemetry, config) == "low_altitude"


def test_cruise_segment_passes_the_altitude_rule() -> None:
    telemetry = heights((0.0, 25.0), (1.0, 28.0), (2.0, 30.0))
    assert apply_rules(segment(0.0, 3.0), metrics(), telemetry, AutocutConfig()) is None


def test_files_without_height_telemetry_are_untouched() -> None:
    telemetry = [TelemetrySample(time_s=0.0, speed_h_ms=1.0)]
    assert apply_rules(segment(), metrics(), telemetry, AutocutConfig()) is None


def test_altitude_only_looks_at_samples_inside_the_segment() -> None:
    telemetry = heights((0.0, 0.5), (10.0, 40.0))
    assert apply_rules(segment(9.0, 12.0), metrics(), telemetry, AutocutConfig()) is None


def test_parked_drone_has_no_motion() -> None:
    config = AutocutConfig()
    assert config.rules.min_motion == pytest.approx(0.02)
    assert apply_rules(segment(), metrics(motion=0.005), None, config) == "no_motion"


def test_handheld_running_is_shaky() -> None:
    config = AutocutConfig()
    result = apply_rules(segment(), metrics(motion=0.7, stability=0.2), None, config)
    assert result == "shaky"


def test_smooth_fast_pan_is_kept() -> None:
    config = AutocutConfig()
    assert apply_rules(segment(), metrics(motion=0.7, stability=0.8), None, config) is None


def test_blown_out_sky_is_clipped() -> None:
    config = AutocutConfig()
    assert config.rules.max_clipped_fraction == pytest.approx(0.05)
    assert apply_rules(segment(), metrics(clipped=0.12), None, config) == "clipped"


def test_the_first_rule_in_order_wins() -> None:
    """A short, low, still and blown out segment reports only the first reason."""
    config = AutocutConfig()
    telemetry = heights((0.0, 0.5))
    result = apply_rules(segment(0.0, 1.0), metrics(motion=0.0, clipped=0.9), telemetry, config)
    assert result == "too_short"


def test_every_reason_is_declared() -> None:
    assert REASONS == ("too_short", "low_altitude", "no_motion", "shaky", "clipped")

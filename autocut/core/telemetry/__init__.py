"""Telemetry adapters: one common time series whatever the camera wrote.

Adapters are selected by probing the file for the data they understand, never by
brand or filename (ADR 3). Adding GoPro GPMF later means adding a module here and
one entry in :data:`ADAPTERS`, with no change to ingest.

``TelemetrySummary`` is defined in :mod:`autocut.core.manifest` because it is a
manifest field type, and re-exported here so the telemetry surface stays in one
place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from autocut.core.manifest import GpsPoint, TelemetryKind, TelemetrySummary
from autocut.core.probe import ProbeResult

__all__ = [
    "adapters",
    "TelemetryAdapter",
    "TelemetrySample",
    "TelemetrySeries",
    "TelemetrySummary",
    "detect_telemetry",
]


class TelemetrySample(BaseModel):
    """One instant of telemetry. Missing fields are ``None``, never zero."""

    time_s: float
    height_m: float | None = None
    speed_h_ms: float | None = None
    speed_v_ms: float | None = None
    lat: float | None = None
    lon: float | None = None
    gps_alt_m: float | None = None
    iso: int | None = None
    shutter: float | None = None
    ev: float | None = None


class TelemetrySeries(BaseModel):
    """All samples parsed from one file, plus what could not be parsed."""

    kind: TelemetryKind
    samples: list[TelemetrySample] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def summary(self) -> TelemetrySummary:
        heights = [s.height_m for s in self.samples if s.height_m is not None]
        speeds = [s.speed_h_ms for s in self.samples if s.speed_h_ms is not None]
        first_fix = next((s for s in self.samples if s.lat is not None and s.lon is not None), None)
        first_gps = (
            GpsPoint(lat=first_fix.lat, lon=first_fix.lon, alt_m=first_fix.gps_alt_m)
            if first_fix is not None and first_fix.lat is not None and first_fix.lon is not None
            else None
        )
        return TelemetrySummary(
            sample_count=len(self.samples),
            min_height_m=min(heights) if heights else None,
            max_height_m=max(heights) if heights else None,
            mean_speed_ms=sum(speeds) / len(speeds) if speeds else None,
            first_gps=first_gps,
            warnings=list(self.warnings),
        )


@runtime_checkable
class TelemetryAdapter(Protocol):
    """Detect and parse one telemetry format."""

    kind: TelemetryKind

    def detect(self, probe: ProbeResult, path: Path) -> bool:
        """True when this adapter understands the data carried by ``path``."""
        ...

    def parse(self, path: Path) -> TelemetrySeries:
        """Read every sample. Unparsable cues are skipped and reported as warnings."""
        ...


def adapters() -> list[TelemetryAdapter]:
    """The adapters to try, in order. Imported lazily to keep the package cycle free."""
    from autocut.core.telemetry.dji import DjiEmbeddedSrtAdapter, DjiSidecarSrtAdapter

    return [DjiEmbeddedSrtAdapter(), DjiSidecarSrtAdapter()]


def detect_telemetry(
    probe: ProbeResult, path: Path
) -> tuple[TelemetryKind, TelemetrySeries | None]:
    """Try adapters in order and parse with the first one that detects its data.

    An adapter that detects its data but parses nothing still wins. Reporting a
    changed or broken cue format as ``none`` would hide it: the file would look
    like it never carried telemetry, and a drone would silently stop being
    rejected on altitude. The empty series carries the warnings instead, and the
    summary shows ``sample_count`` 0.
    """
    for adapter in adapters():
        if adapter.detect(probe, path):
            series = adapter.parse(path)
            if not series.samples:
                series.warnings.append(f"{adapter.kind} detected but no sample could be parsed")
            return adapter.kind, series
    return "none", None

"""Manifest schema: the single source of truth and project file.

See SPEC.md section 9 and ADR 5 for why segments store a best window center
rather than final in and out points.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from autocut.core.config import SourceClass

MANIFEST_SCHEMA_VERSION = 1
ANALYSIS_SCHEMA_VERSION = 1

Outcome = Literal["candidate", "selected", "rejected"]
TelemetryKind = Literal["dji_embedded_srt", "dji_sidecar_srt", "gopro_gpmf", "none"]


class GpsPoint(BaseModel):
    lat: float
    lon: float
    alt_m: float | None = None


class StreamInfo(BaseModel):
    """A non-video stream seen by ffprobe, kept so adapters can find their data."""

    index: int
    codec_type: str
    codec_name: str | None = None
    codec_tag: str | None = None
    handler_name: str | None = None
    language: str | None = None


class TelemetrySummary(BaseModel):
    """Aggregate of a file's telemetry. Full samples live in the analysis cache."""

    sample_count: int = 0
    min_height_m: float | None = None
    max_height_m: float | None = None
    mean_speed_ms: float | None = None
    first_gps: GpsPoint | None = None
    warnings: list[str] = Field(default_factory=list)


class SourceFile(BaseModel):
    """One raw video file and what ingest learned about it."""

    id: str = Field(description="Cache key, see ADR 6.")
    path: Path
    proxy_path: Path | None = None
    source_class: SourceClass = "generic"
    class_signal: str = "default"
    class_overridden: bool = False
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    rotation: int = 0
    fps: float = 0.0
    codec: str = ""
    pix_fmt: str = ""
    bit_depth: int = 8
    creation_time: datetime | None = None
    make: str | None = None
    model: str | None = None
    gps: GpsPoint | None = None
    telemetry: TelemetryKind = "none"
    telemetry_summary: TelemetrySummary | None = None
    subtitle_streams: list[StreamInfo] = Field(default_factory=list)
    data_streams: list[StreamInfo] = Field(default_factory=list)
    error: str | None = None

    @property
    def display_width(self) -> int:
        return self.height if self.rotation % 180 == 90 else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation % 180 == 90 else self.height

    @property
    def is_vertical(self) -> bool:
        """Orientation as the viewer sees it, rotation side data applied."""
        return self.display_height > self.display_width


class Metrics(BaseModel):
    """Per segment aggregates. Raw per frame arrays live in the cache."""

    sharpness: float
    exposure_clipped: float
    motion: float
    stability: float
    colorfulness: float
    aesthetic: float | None = None
    faces: int | None = None
    min_height_m: float | None = None
    mean_speed_ms: float | None = None


class Segment(BaseModel):
    """A candidate clip: a scene detected span within a source file.

    ``start_s`` and ``end_s`` are the bounds shot detection found. ``trimmed_start_s``
    and ``trimmed_end_s`` are those bounds after the per-class head and tail trim, and
    they are what every later stage works with. See ADR 5 for why no final duration is
    stored here.
    """

    id: str
    file_id: str
    start_s: float
    end_s: float
    trimmed_start_s: float | None = None
    trimmed_end_s: float | None = None
    frame_count: int = 0
    analyzed_from: Literal["proxy", "original"] | None = None
    split_reason: str | None = Field(
        default=None,
        description="Why this span was cut out of its shot, e.g. 'altitude'. None when "
        "the segment is a whole detected shot.",
    )
    best_center_s: float | None = None
    target_duration_s: float | None = None
    metrics: Metrics | None = None
    score: float | None = None
    outcome: Outcome = "candidate"
    reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    caption: str | None = None
    embedding_ref: str | None = None
    cluster_id: int | None = None
    thumbnail: Path | None = None
    sprite: Path | None = None
    order: int | None = None
    final_start_s: float | None = None
    final_end_s: float | None = None
    exported_path: Path | None = None


class AnalysisRun(BaseModel):
    """What the last analysis pass did.

    The report header reports how many files were served from the cache, and that
    is a property of the run rather than of any file, so it is recorded here.
    """

    files_analyzed: int = 0
    files_from_cache: int = 0
    files_failed: int = 0
    completed: bool = True


class Soundtrack(BaseModel):
    proposed_bpm: float | None = None
    measured_bpm: float | None = None
    bpm_override: float | None = None
    audio_path: Path | None = None
    beats_s: list[float] = Field(default_factory=list)
    prompt_path: Path | None = None


class Manifest(BaseModel):
    """Root document written to ``manifest.json``."""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    analysis_schema_version: int = ANALYSIS_SCHEMA_VERSION
    created_at: datetime
    updated_at: datetime
    sources: list[Path]
    output_dir: Path
    files: dict[str, SourceFile] = Field(default_factory=dict)
    segments: dict[str, Segment] = Field(default_factory=dict)
    analysis: AnalysisRun = AnalysisRun()
    soundtrack: Soundtrack = Soundtrack()
    config_snapshot: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

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


class SourceFile(BaseModel):
    """One raw video file and what ingest learned about it."""

    id: str = Field(description="Cache key, see ADR 6.")
    path: Path
    proxy_path: Path | None = None
    source_class: SourceClass = "generic"
    class_overridden: bool = False
    duration_s: float
    width: int
    height: int
    rotation: int = 0
    fps: float
    codec: str
    pix_fmt: str
    bit_depth: int = 8
    creation_time: datetime | None = None
    make: str | None = None
    model: str | None = None
    gps: GpsPoint | None = None
    telemetry: TelemetryKind = "none"


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
    """A candidate clip: a scene detected span within a source file."""

    id: str
    file_id: str
    start_s: float
    end_s: float
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

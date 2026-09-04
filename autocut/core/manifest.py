"""Manifest schema: the single source of truth and project file.

See SPEC.md section 9 and ADR 5 for why segments store a best window center
rather than final in and out points.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from autocut.core.config import CutMode, SourceClass

MANIFEST_SCHEMA_VERSION = 1
ANALYSIS_SCHEMA_VERSION = 1

Outcome = Literal["candidate", "selected", "rejected"]
TagSource = Literal["local", "cloud"]
DurationReason = Literal["base", "hero", "alternation", "total", "clamped", "override", "beat"]
TelemetryKind = Literal["dji_embedded_srt", "dji_sidecar_srt", "gopro_gpmf", "none"]


class Tag(BaseModel):
    """One label on a segment, with how sure it is and where it came from.

    The source is here from the first tag rather than added when the second producer
    arrives, because a later source must not silently delete another source's tags and
    that rule needs somewhere to read the provenance from.

    ``primary`` says this tag came from the group that names the clip. It is stored
    rather than derived so that naming and the report can read a manifest without the
    configuration that produced it: which group is primary is a setting, and a project
    opened later must still name its clips the way it exported them.
    """

    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: TagSource = "local"
    group: str | None = Field(
        default=None,
        description="Which label group scored this tag. None for a source that does "
        "not group, such as a cloud vision model.",
    )
    primary: bool = Field(
        default=False,
        description="Whether this tag can be the dominant one. A view or lighting tag "
        "describes the shot without naming its subject, so it never is.",
    )


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
    duration_reason: DurationReason | None = Field(
        default=None,
        description="Which rule settled this clip's length, so the report can explain "
        "it in one word.",
    )
    beats: int | None = Field(
        default=None,
        description="How many beats of the track this clip lasts, once beat sync has "
        "rounded its length. None until sync runs.",
    )
    snapped: bool = Field(
        default=False,
        description="Whether the window start was moved onto a motion minimum, so the "
        "cut lands where movement begins rather than partway through it.",
    )
    metrics: Metrics | None = None
    score: float | None = None
    outcome: Outcome = "candidate"
    reason: str | None = None
    tags: list[Tag] = Field(
        default_factory=list,
        description="Semantic labels, highest confidence first.",
    )
    caption: str | None = None
    description_error: str | None = Field(
        default=None,
        description="Why a cloud description failed for this segment. Kept so a report "
        "can show which clips a provider outage left without a caption.",
    )
    embedding_ref: str | None = None
    cluster_id: int | None = None
    place_id: int | None = Field(
        default=None,
        description="Which spot this was shot at, from GPS. Null when the file carries "
        "no position, in which case no place cap applies to it.",
    )
    visit_id: int | None = Field(
        default=None,
        description="Which outing to that spot. The same beach on another day is a "
        "different visit and gets its own clips.",
    )
    held_by: list[str] = Field(
        default_factory=list,
        description="Ids of the selected clips that filled this candidate's visit, so "
        "the report can name what it lost to rather than only that it lost.",
    )
    similarity_to_selected: float | None = Field(
        default=None,
        description="Highest similarity to any selected segment, so the report can "
        "show how close a candidate came to being a duplicate.",
    )
    lost_to: str | None = Field(
        default=None, description="Id of the selected near duplicate this candidate lost to."
    )
    thumbnail: Path | None = None
    sprite: Path | None = None
    order: int | None = None
    final_start_s: float | None = None
    final_end_s: float | None = None
    exported_path: Path | None = None
    export_mode: CutMode | None = Field(
        default=None,
        description="How this clip was cut. 'fast' means the bounds are keyframe "
        "aligned and the duration is approximate.",
    )
    export_fingerprint: str | None = Field(
        default=None,
        description="Digest of everything the output depends on. A re-run skips the "
        "clip when this still matches, which is what makes export resumable.",
    )
    export_error: str | None = None
    fps_converted: bool = Field(
        default=False,
        description="True when the source frame rate is neither the export target nor "
        "a whole multiple of it, so frames had to be resampled.",
    )

    @field_validator("tags", mode="before")
    @classmethod
    def _upgrade_string_tags(cls, value: object) -> object:
        """Read a manifest written before tags carried a confidence and a source.

        M2 wrote ``tags`` as a list of strings. Upgrading them here rather than by a
        schema bump keeps every M2 project openable: the shape changed, what a tag
        means did not, and a string tag was always something a person wrote by hand.
        """
        if not isinstance(value, list):
            return value
        return [
            {"label": item, "confidence": 1.0, "source": "local", "primary": True}
            if isinstance(item, str)
            else item
            for item in value
        ]

    @property
    def dominant_tag(self) -> str | None:
        """The tag that names this clip, or ``None`` when nothing named its subject.

        Only a primary tag can be dominant. A shot that is confidently ``aerial`` and
        confidently nothing else is still a clip whose subject is unknown, and calling
        the file ``aerial`` would say what the source class already says.

        Derived rather than stored: it changes whenever the tag list does, and a stored
        copy would be one more thing to keep in step. ``m3-cloud-providers`` gives cloud
        tags precedence here.
        """
        primary = [tag for tag in self.tags if tag.primary]
        if not primary:
            return None
        # A cloud tag wins when there is one, in the order the model returned them: a
        # vision model looking at the picture is more specific than a zero-shot label
        # set, and its first tag is its own answer to "what is this".
        cloud = [tag for tag in primary if tag.source == "cloud"]
        if cloud:
            return cloud[0].label
        return max(primary, key=lambda tag: tag.confidence).label

    @property
    def secondary_tags(self) -> list[Tag]:
        """Everything that describes the shot without naming its subject."""
        return [tag for tag in self.tags if not tag.primary]


class AnalysisRun(BaseModel):
    """What the last analysis pass did.

    The report header reports how many files were served from the cache, and that
    is a property of the run rather than of any file, so it is recorded here. So
    is the decoder: it is chosen once per run, and recording it is what makes
    timings comparable between machines.
    """

    files_analyzed: int = 0
    files_from_cache: int = 0
    files_failed: int = 0
    completed: bool = True
    hwaccel: str = "none"
    embedding_model: str = Field(
        default="none",
        description="Which model produced the segment embeddings, or 'none' when the "
        "ai extra was missing or embeddings were switched off.",
    )
    embedding_device: str = Field(
        default="none",
        description="Which compute device embedded them, so a timing on the MacBook "
        "and one on the Linux box can be told apart.",
    )
    cloud_model: str = Field(
        default="none",
        description="Which hosted model described the segments, or 'none' when cloud "
        "was switched off, no key was available or nothing needed describing.",
    )
    cloud_requests: int = Field(
        default=0, description="Requests actually issued. A cached run issues none."
    )
    cloud_cost_usd: float = Field(
        default=0.0,
        description="Cost of those requests from the usage the provider reported, so a "
        "project says what it cost without anyone opening a dashboard.",
    )
    warnings: list[str] = Field(default_factory=list)


class SelectionRun(BaseModel):
    """The parameters the last selection used, so a manifest explains its own picks."""

    ran_at: datetime | None = None
    diversity_lambda: float | None = None
    max_clips: int | None = None
    target_duration_s: float | None = None
    places: int = 0
    visits: int = 0
    total_duration_s: float | None = Field(
        default=None,
        description="Length of the edit, the sum of the selected clips' target durations. "
        "The soundtrack prompt in M4 needs it before any track exists.",
    )
    selected: int = 0
    clusters: int = 0


class ExportRun(BaseModel):
    """What the last export produced, and the settings every clip in it shares.

    ``target_fps`` is recorded rather than recomputed because it is the mode of the
    selected clips' frame rates: deselecting one clip could otherwise flip the target
    and silently invalidate every output that was already written.
    """

    ran_at: datetime | None = None
    target_fps: float | None = None
    max_width: int | None = None
    max_height: int | None = None
    mode: CutMode | None = None
    codec: str | None = None
    exported: int = 0
    skipped: int = 0
    failed: int = 0
    slow_motion: int = 0
    fps_converted: int = 0
    stale_moved: int = 0
    warnings: list[str] = Field(default_factory=list)


class PlaceInfo(BaseModel):
    """One place the footage was shot at, with the name reverse geocoding gave it.

    Named ``PlaceInfo`` rather than ``Place`` because :mod:`autocut.core.places` already
    has a ``Place`` for the grouping itself, and the two live in the same call stack.

    Places are numbered by selection from GPS clusters; the name and region are added
    later and separately, because geocoding needs the network and selection must not.
    """

    place_id: int
    lat: float | None = None
    lon: float | None = None
    name: str | None = None
    region: str | None = None
    segments: int = 0
    geocode_error: str | None = None

    @property
    def label(self) -> str:
        """What to call this place in a prompt or a report, named or not."""
        return self.name or f"place {self.place_id}"


class SoundtrackSignals(BaseModel):
    """What the edit is, as the numbers and words a prompt is written from.

    Stored on the manifest so a prompt can be explained after the fact and so the
    refinement step has something to send that is not the footage.
    """

    total_duration_s: float = 0.0
    clip_count: int = 0
    energy_curve: list[float] = Field(
        default_factory=list, description="One smoothed value per clip in edit order, 0 to 1."
    )
    energy_band: str = "mid"
    peak_third: int = Field(
        default=1, description="Which third of the edit holds the highest energy, 0 to 2."
    )
    dominant_tag: str | None = None
    dominant_tag_share: float = 0.0
    tags: dict[str, int] = Field(default_factory=dict)
    captions: list[str] = Field(default_factory=list)
    class_mix: dict[str, float] = Field(default_factory=dict)
    time_of_day: str = "daytime"
    place_names: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)


class PromptVariant(BaseModel):
    """One Suno prompt, ready to paste into the two fields of custom mode."""

    title: str
    description: str
    structure: list[str]
    mood: list[str] = Field(default_factory=list)
    instruments: list[str] = Field(default_factory=list)
    source: Literal["template", "refined"] = "template"


class Soundtrack(BaseModel):
    proposed_bpm: float | None = None
    measured_bpm: float | None = None
    bpm_override: float | None = None
    audio_path: Path | None = None
    beats_s: list[float] = Field(default_factory=list)
    prompt_path: Path | None = None
    signals: SoundtrackSignals | None = None
    matched_row: str | None = Field(
        default=None,
        description="Which genre row was chosen, so a surprising genre traces to one "
        "line of configuration.",
    )
    matched_reason: str | None = Field(
        default=None, description="Why that row matched, in the words of its conditions."
    )
    genre: str | None = None
    beat_distance: float | None = Field(
        default=None,
        description="Mean distance of the clip lengths from a whole beat at the proposed "
        "BPM, in beats. Zero means every clip lands on the grid.",
    )
    variants: list[PromptVariant] = Field(default_factory=list)
    chosen_variant: int = 0
    refinement: Literal["off", "skipped", "accepted", "rejected", "failed"] = "off"
    refinement_note: str | None = None
    comparison: str | None = Field(
        default=None,
        description="How the measured BPM compared to the proposed one: 'agreed', "
        "'drifted', 'half', 'double', or 'no proposal'. Kept so the report can show it "
        "without redoing the arithmetic.",
    )
    comparison_note: str | None = None
    beatmap_path: Path | None = None


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
    places: dict[str, PlaceInfo] = Field(
        default_factory=dict,
        description="Keyed by the place id as a string, because JSON object keys are "
        "strings and a round trip must not change the type.",
    )
    analysis: AnalysisRun = AnalysisRun()
    selection: SelectionRun = SelectionRun()
    export: ExportRun = ExportRun()
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

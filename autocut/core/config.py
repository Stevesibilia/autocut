"""Configuration schema for ``autocut.toml``.

Every tunable named in SPEC.md lives here with its default. Weights and thresholds
are deliberately not hardcoded elsewhere: they are tuned on real footage.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

SourceClass = Literal["drone", "actioncam", "phone", "reflex", "generic"]
VerticalStrategy = Literal["exclude", "blur_pad", "center_crop"]
CutMode = Literal["precise", "fast"]

SOURCE_CLASSES: tuple[SourceClass, ...] = ("drone", "actioncam", "phone", "reflex", "generic")

T = TypeVar("T")


class PerClass(BaseModel, Generic[T]):
    """A value that differs per source class."""

    drone: T
    actioncam: T
    phone: T
    reflex: T
    generic: T

    def get(self, source_class: SourceClass) -> T:
        return getattr(self, source_class)  # type: ignore[no-any-return]


class ClassOverride(BaseModel):
    """Manual source class assignment for files matching a glob."""

    glob: str
    source_class: SourceClass


class AnalysisConfig(BaseModel):
    sample_fps: float = 2.0
    sample_long_side: int = 320
    use_proxies: bool = True
    hwaccel: Literal["auto", "off"] = "auto"
    workers: int | None = Field(default=None, description="Defaults to physical cores.")
    sprites: bool = False
    sprite_max_frames: int = 60
    thumbnail_quality: int = 85
    detector: Literal["inmemory", "pyscenedetect"] = "inmemory"
    scene_threshold: float = Field(
        default=0.30,
        description="Content difference above which a cut is declared, 0 to 1. "
        "Tuned for frames half a second apart, not for adjacent frames.",
    )
    min_scene_seconds: float = 1.0
    stability_window: int = Field(default=5, description="Frames in the motion std window.")
    sharpness_center_crop: float = Field(
        default=0.6, description="Share of width and height kept for actioncam sharpness."
    )
    head_trim_seconds: PerClass[float] = PerClass(
        drone=1.0, actioncam=1.0, phone=0.3, reflex=0.5, generic=0.5
    )
    tail_trim_seconds: PerClass[float] = PerClass(
        drone=1.0, actioncam=1.0, phone=0.3, reflex=0.5, generic=0.5
    )
    class_overrides: list[ClassOverride] = Field(default_factory=list)


class ScoringWeights(BaseModel):
    sharpness: float = 1.0
    exposure: float = 1.0
    motion: float = 1.0
    stability: float = 1.0
    colorfulness: float = 0.5
    aesthetic: float = 0.0
    faces: float = 0.0


class DroneRules(BaseModel):
    min_height_m: float = 5.0


class RejectionRules(BaseModel):
    drone: DroneRules = DroneRules()
    min_motion: float = 0.02
    max_motion: float = 0.6
    min_stability: float = 0.3
    max_clipped_fraction: float = 0.05


class SelectionConfig(BaseModel):
    min_segment_seconds: float = 1.5
    target_duration_seconds: float = 3.0
    max_clips: int = 40
    max_clips_per_file: PerClass[int] = PerClass(drone=1, actioncam=3, phone=1, reflex=2, generic=1)
    min_share_per_class: PerClass[float] = PerClass(
        drone=0.0, actioncam=0.0, phone=0.0, reflex=0.0, generic=0.0
    )
    diversity_lambda: float = 0.6
    max_clips_per_cluster: int = 2
    min_temporal_gap_seconds: float = 60.0


class SimilarityConfig(BaseModel):
    visual_semantic: bool = True
    visual_fallback: bool = True
    spatial: bool = True
    temporal: bool = True
    motion: bool = True


class SoundtrackConfig(BaseModel):
    variants: int = 3
    bpm_tolerance: float = 3.0
    beat_multiples: list[int] = Field(default_factory=lambda: [2, 4, 8])
    alternate_durations: bool = True
    genres: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "aerial_landscape": {
                "genre": "cinematic ambient",
                "instruments": "sweeping strings, soft piano",
                "bpm_range": "80-100",
            },
            "beach_family": {
                "genre": "indie folk",
                "instruments": "acoustic guitar, warm ukulele",
                "bpm_range": "100-120",
            },
            "action_water": {
                "genre": "tropical house",
                "instruments": "plucked synth, deep bass",
                "bpm_range": "115-125",
            },
        },
        description="Placeholder genre table, tune to taste.",
    )


class ExportConfig(BaseModel):
    mode: CutMode = "precise"
    codec: Literal["libx264", "libx265", "h264_videotoolbox", "h264_vaapi"] = "libx264"
    crf: int = 18
    fps: Literal["auto"] | float = "auto"
    max_width: int = 3840
    max_height: int = 2160
    pix_fmt: Literal["yuv420p", "passthrough"] = "yuv420p"
    remove_audio: PerClass[bool] = PerClass(
        drone=True, actioncam=True, phone=False, reflex=False, generic=True
    )
    slow_motion_auto: PerClass[bool] = PerClass(
        drone=False, actioncam=True, phone=False, reflex=False, generic=False
    )
    vertical_strategy: VerticalStrategy = "exclude"
    lut: PerClass[Path | None] = PerClass(
        drone=None, actioncam=None, phone=None, reflex=None, generic=None
    )
    lens_correction: PerClass[bool] = PerClass(
        drone=False, actioncam=False, phone=False, reflex=False, generic=False
    )
    keep_rejects: bool = False


class ProvidersConfig(BaseModel):
    cloud: bool = True
    vision_model: str = "google/gemini-2.5-flash"
    llm_model: str = "google/gemini-2.5-flash"
    local_embeddings: bool = True
    embedding_model: str = "ViT-B-32/laion2b_s34b_b79k"
    aesthetic: bool = False
    faces: bool = False


class CacheConfig(BaseModel):
    dir: Path | None = Field(default=None, description="Defaults to the platform cache dir.")


class AutocutConfig(BaseModel):
    """Root configuration model."""

    analysis: AnalysisConfig = AnalysisConfig()
    weights: ScoringWeights = ScoringWeights()
    rules: RejectionRules = RejectionRules()
    selection: SelectionConfig = SelectionConfig()
    similarity: SimilarityConfig = SimilarityConfig()
    soundtrack: SoundtrackConfig = SoundtrackConfig()
    export: ExportConfig = ExportConfig()
    providers: ProvidersConfig = ProvidersConfig()
    cache: CacheConfig = CacheConfig()

    @classmethod
    def load(cls, path: Path | None) -> AutocutConfig:
        """Load ``autocut.toml`` or return defaults when ``path`` is ``None`` or missing."""
        if path is None or not path.exists():
            return cls()
        with path.open("rb") as fh:
            return cls.model_validate(tomllib.load(fh))

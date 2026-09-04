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
    hwaccel: Literal["auto", "off", "vaapi", "videotoolbox"] = Field(
        default="auto",
        description=(
            "Decoder for sampling, chosen once per run and verified on the first file. "
            '"auto" selects videotoolbox on macOS and software elsewhere: vaapi decodes '
            "correctly on Linux but measured slower than software for 2 fps sampling, so "
            'it has to be asked for by name. "off" forces software.'
        ),
    )
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
    # Zero by default: on well exposed SDR footage clipping is effectively zero on
    # every segment, so ranking on it sorts noise. It stays a rejection rule.
    exposure: float = 0.0
    motion: float = 1.0
    stability: float = 1.0
    colorfulness: float = 0.5
    aesthetic: float = 0.0
    faces: float = 0.0


class DroneRules(BaseModel):
    min_height_m: float = 5.0


class RejectionRules(BaseModel):
    """Thresholds set from the measured distribution on the Sardinia set.

    Each description says what share of the 77 pooled Sardinia segments falls below the
    value, which is not the same number as the value at that percentile: 0.015 leaves
    7.8% of segments below it, while the value at the 7.8th percentile is 0.0190. The
    full table is in the m2-scoring-tuning task list. They are defaults, not constants:
    re-run ``scripts/metric_stats.py`` on new footage before trusting them elsewhere.
    """

    drone: DroneRules = DroneRules()
    min_motion: float = Field(
        default=0.015, description="Below it: 6 of the 77 Sardinia segments, a share of 7.8%."
    )
    shaky_min_motion: float = Field(
        default=0.04,
        description="Below it: 20 of the 77 Sardinia segments, a share of 26.0%. Below this "
        "a wobble is a still shot, so the no_motion rule describes it better than shaky.",
    )
    min_stability: float = Field(
        default=0.71,
        description="Below it: 8 of the 77 Sardinia segments, a share of 10.4%.",
    )
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
    cluster_threshold: float = Field(
        default=0.75,
        description="Combined similarity above which two candidates join one visual cluster.",
    )
    duration_by_class: PerClass[float] = Field(
        default=PerClass(drone=4.0, actioncam=2.0, phone=2.5, reflex=3.0, generic=3.0),
        description="Base seconds per class before the score scales it. An aerial needs "
        "longer to be read than an action shot, which is the difference these encode. "
        "A class set to 0 falls back to target_duration_seconds.",
    )
    duration_min_seconds: float = 1.5
    duration_max_seconds: float = 6.0
    score_duration_range: tuple[float, float] = Field(
        default=(0.8, 1.2),
        description="Multiplier at score 0 and at score 1. Narrow on purpose: the class "
        "base sets the rhythm and the score only nudges it, because a wide range would "
        "make a weak drone shot shorter than a strong action shot.",
    )
    hero_share: float = Field(
        default=0.1, description="Share of the selection, by score, that gets the hero bonus."
    )
    hero_multiplier: float = 1.5
    alternate_durations: bool = Field(
        default=True,
        description="Break runs of three clips in the same duration bucket, so the edit "
        "does not settle into one rhythm.",
    )
    target_total_seconds: float | None = Field(
        default=None,
        description="When set, every duration is scaled by one factor so the edit lands "
        "near this length. Off by default: the length follows from the clips.",
    )
    place_radius_m: float = Field(
        default=150.0,
        description="Two candidates this close share a place, transitively. Smaller than "
        "the spatial similarity radius on purpose: that signal is a soft penalty and "
        "this is a hard cap.",
    )
    place_visit_gap_seconds: float = Field(
        default=7200.0,
        description="A gap this long inside one place starts a new visit. Coming back to "
        "the same beach the next day deserves its own clips.",
    )
    max_clips_per_place: int = Field(
        default=3,
        description="Clips from one visit to one place. Three keeps a wide, a medium and "
        "a detail, which is how a montage covers a location.",
    )
    max_share_per_tag: float = Field(
        default=0.5,
        description="Ceiling on the share of the final count carrying one dominant "
        "tag, while candidates with another tag or none remain. Lifted when nothing "
        "else is eligible, like the place cap and the temporal gap.",
    )
    max_candidate_share: float = Field(
        default=0.5,
        description="Ceiling on max_clips as a share of the eligible candidates, so a "
        "small folder does not select most of what survived the rules. An explicit "
        "--max-clips overrides it.",
    )
    snap_to_motion: bool = True
    snap_window_seconds: float = Field(
        default=0.5, description="How far the window start may move to reach a motion minimum."
    )
    snap_max_score_loss: float = Field(
        default=0.05,
        description="Mean score a snap may give up, as a share. The window search already "
        "found the best frames, so the snap is only allowed to fix where the cut lands.",
    )


class TagLabel(BaseModel):
    """One zero-shot label and, when the group template reads badly, its own prompt."""

    label: str
    prompt: str | None = Field(
        default=None,
        description="Full sentence to encode instead of the group template. CLIP is "
        "sensitive to phrasing, and some labels need more context than the word alone.",
    )


class TagGroup(BaseModel):
    """Labels that are alternatives to each other, scored by one softmax.

    Groups exist because a drone shot over a beach is a beach and is aerial, and one
    softmax over both makes them compete for the same probability mass. Anything that
    can be true at the same time as another label belongs in another group.

    ``null_prompt`` joins the softmax and is never emitted. Without it the probabilities
    of a group always sum to one over its labels, so some label always wins however
    little the picture has to do with any of them, and the threshold decides nothing.
    """

    name: str
    prompt_template: str = "a photo of {label}"
    null_prompt: str = Field(
        description="Encoded with the labels and never emitted: the way a group says none of these."
    )
    primary: bool = Field(
        default=False,
        description="Whether this group provides the dominant tag, the one that names "
        "the exported clip. Exactly one group should be primary.",
    )
    labels: list[TagLabel]


DEFAULT_TAG_GROUPS: tuple[TagGroup, ...] = (
    TagGroup(
        name="subject",
        null_prompt="a photo",
        primary=True,
        labels=[
            TagLabel(label="beach"),
            TagLabel(label="mountain"),
            TagLabel(label="city"),
            TagLabel(label="street"),
            TagLabel(label="indoor"),
            TagLabel(label="food"),
            TagLabel(label="people"),
        ],
    ),
    TagGroup(
        name="view",
        null_prompt="a photo taken at ground level",
        labels=[
            # "aerial" alone encodes closer to an antenna than to a view from the air.
            TagLabel(label="aerial", prompt="an aerial photo taken from a drone"),
            TagLabel(label="underwater"),
        ],
    ),
    TagGroup(
        name="light",
        null_prompt="a photo taken in ordinary daylight",
        labels=[TagLabel(label="sunset")],
    ),
)


class TagsConfig(BaseModel):
    """Zero-shot labels, their groups and how confident a tag has to be to stick."""

    enabled: bool = True
    logit_scale: float = Field(
        default=10.0,
        description="Cosines are multiplied by this before the softmax. CLIP ships 100, "
        "which is the constant its contrastive loss was trained with and produces a "
        "one-hot distribution over a handful of labels: measured on the Sardinia set at "
        "100, every segment took a tag and no threshold rejected anything. 10 leaves the "
        "probabilities spread widely enough for a threshold to mean something.",
    )
    threshold: float = Field(
        default=0.2,
        description="Probability after the softmax over a group, its null prompt "
        "included. Not a cosine: the useful cosine range shifts with the label set, a "
        "probability does not.",
    )
    max_per_segment: int = Field(
        default=3,
        description="Tags kept in total, across groups. The dominant tag is kept first "
        "and the rest fill by confidence.",
    )
    groups: list[TagGroup] = Field(default_factory=lambda: list(DEFAULT_TAG_GROUPS))

    @property
    def primary_group(self) -> str | None:
        """The group whose top tag names the clip."""
        for group in self.groups:
            if group.primary:
                return group.name
        return None


class SimilarityWeights(BaseModel):
    """Relative weight of each similarity signal. Placeholders until tuned on footage."""

    visual: float = 0.5
    # The semantic signal replaces the visual one for a pair rather than joining it, so
    # it carries the same weight: the two answer the same question and only one of them
    # answers it well.
    semantic: float = 0.5
    spatial: float = 0.2
    temporal: float = 0.2
    motion: float = 0.1


class SimilarityConfig(BaseModel):
    visual_semantic: bool = True
    visual_fallback: bool = True
    spatial: bool = True
    temporal: bool = True
    motion: bool = True
    weights: SimilarityWeights = SimilarityWeights()
    spatial_radius_m: float = Field(
        default=200.0, description="GPS distance at which the spatial signal reaches 0."
    )
    temporal_radius_s: float = Field(
        default=600.0, description="Time distance at which the temporal signal reaches 0."
    )
    semantic_floor: float = Field(
        default=0.5,
        description="Cosine similarity mapped to 0. CLIP vectors of two unrelated "
        "holiday shots still sit around 0.5, so the useful range is the half above "
        "it and stretching that half is what makes the signal discriminate.",
    )


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
    remove_audio: PerClass[bool] = Field(
        default=PerClass(drone=True, actioncam=True, phone=True, reflex=True, generic=True),
        description="A default export is silent and the soundtrack carries the sound. Set "
        "a class to false to keep its ambience.",
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
    embedding_model: str = Field(
        default="ViT-B-32/laion2b_s34b_b79k",
        description="Vision model as architecture/pretrained. 512 dimensions and about "
        "350 MB; a larger tower costs several times the CPU time for a marginal gain at "
        "a few hundred segments. Changing this recomputes embeddings from cached frames "
        "and leaves the metric arrays alone.",
    )
    embedding_batch_size: int = Field(
        default=16, description="Frames per forward pass. They are already in memory."
    )
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
    tags: TagsConfig = TagsConfig()
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

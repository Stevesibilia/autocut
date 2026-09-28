"""Configuration schema for ``autocut.toml``.

Every tunable named in SPEC.md lives here with its default. Weights and thresholds
are deliberately not hardcoded elsewhere: they are tuned on real footage.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceClass = Literal["drone", "actioncam", "phone", "reflex", "generic"]
VerticalStrategy = Literal["exclude", "blur_pad", "center_crop"]
CutMode = Literal["precise", "fast"]

SOURCE_CLASSES: tuple[SourceClass, ...] = ("drone", "actioncam", "phone", "reflex", "generic")


class _Strict(BaseModel):
    """Base for every configuration model: an unknown key is a mistake, not a typo to ignore."""

    model_config = ConfigDict(extra="forbid")


class PerClass[T](_Strict):
    """A value that differs per source class."""

    drone: T
    actioncam: T
    phone: T
    reflex: T
    generic: T

    def get(self, source_class: SourceClass) -> T:
        return getattr(self, source_class)  # type: ignore[no-any-return]


class ClassOverride(_Strict):
    """Manual source class assignment for files matching a glob."""

    glob: str
    source_class: SourceClass


class AnalysisConfig(_Strict):
    sample_fps: float = Field(default=2.0, gt=0)
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
    workers: int | None = Field(default=None, ge=1, description="Defaults to physical cores.")
    sprites: bool = False
    sprite_max_frames: int = Field(default=60, ge=1)
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
    high_fps_threshold: float = Field(
        default=100.0,
        gt=0,
        description="A frame rate at or above this only comes from a camera built for "
        "slow motion, and classifies an otherwise unrecognized file as actioncam.",
    )
    fallback_fps: float = Field(
        default=25.0,
        gt=0,
        description="Frame rate assumed for the pyscenedetect minimum scene length when "
        "ffprobe reports none.",
    )


class ScoringWeights(_Strict):
    sharpness: float = 1.0
    # Zero by default: on well exposed SDR footage clipping is effectively zero on
    # every segment, so ranking on it sorts noise. It stays a rejection rule.
    exposure: float = 0.0
    motion: float = 1.0
    stability: float = 1.0
    colorfulness: float = 0.5
    aesthetic: float = 0.0
    faces: float = 0.0


class DroneRules(_Strict):
    min_height_m: float = 5.0


class RejectionRules(_Strict):
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


class SelectionConfig(_Strict):
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


class TagLabel(_Strict):
    """One zero-shot label and, when the group template reads badly, its own prompt."""

    label: str
    prompt: str | None = Field(
        default=None,
        description="Full sentence to encode instead of the group template. CLIP is "
        "sensitive to phrasing, and some labels need more context than the word alone.",
    )


class TagGroup(_Strict):
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


class TagsConfig(_Strict):
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


class SimilarityWeights(_Strict):
    """Relative weight of each similarity signal. Placeholders until tuned on footage."""

    visual: float = 0.5
    # The semantic signal replaces the visual one for a pair rather than joining it, so
    # it carries the same weight: the two answer the same question and only one of them
    # answers it well.
    semantic: float = 0.5
    spatial: float = 0.2
    temporal: float = 0.2
    motion: float = 0.1


class SimilarityConfig(_Strict):
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
    histogram_bins: int = Field(
        default=8, ge=2, le=32, description="Per channel buckets of the fallback colour histogram."
    )
    hash_share: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Share of the visual fallback signal that comes from the perceptual "
        "hash. The colour histogram gets the rest.",
    )


EnergyBand = Literal["low", "mid", "high"]
TimeOfDay = Literal["morning", "daytime", "evening", "night"]


class GenreWhen(_Strict):
    """What has to be true of an edit for a genre row to apply.

    Every field is optional and an absent field is not a condition. A row with an empty
    ``when`` matches anything, which is what makes the last row a default.
    """

    tags_any: list[str] = Field(
        default_factory=list, description="At least one of these tags is on the edit."
    )
    tags_dominant: list[str] = Field(
        default_factory=list, description="The edit's dominant tag is one of these."
    )
    class_min_share: dict[SourceClass, float] = Field(
        default_factory=dict, description="Each named class holds at least this share."
    )
    energy: list[EnergyBand] = Field(default_factory=list)
    time_of_day: list[TimeOfDay] = Field(default_factory=list)
    region_any: list[str] = Field(
        default_factory=list,
        description="A place region contains one of these, case insensitively. Needs "
        "geocoding to have run.",
    )


class GenreRow(_Strict):
    """One row of the genre table: when it applies and what it asks the model for."""

    name: str
    genre: str
    instruments: list[str] = Field(
        description="Adjective plus instrument, as Suno wants them: 'twangy guitar', "
        "never 'guitar'. Two or three."
    )
    bpm: tuple[int, int]
    mood: list[str]
    when: GenreWhen = GenreWhen()
    mood_alternates: list[str] = Field(
        default_factory=list, description="Swapped in to make a variant differ in mood."
    )
    instrument_alternates: list[str] = Field(
        default_factory=list, description="Swapped in to make a variant differ in sound."
    )


#: Ordered specific to general, first match wins, the default last. Seeded from the
#: user's own list of genres. These are data: editing a row needs no code change, and
#: the report says which row matched so a surprising choice can be traced to one line.
DEFAULT_GENRE_ROWS: tuple[GenreRow, ...] = (
    GenreRow(
        name="surf rock",
        genre="surf rock",
        instruments=["twangy reverb guitar", "driving drums", "warm bass"],
        bpm=(120, 140),
        mood=["sunny", "carefree"],
        mood_alternates=["breezy", "playful"],
        instrument_alternates=["shimmering tremolo guitar"],
        when=GenreWhen(tags_dominant=["beach"], tags_any=["underwater"], energy=["mid", "high"]),
    ),
    GenreRow(
        name="pop punk",
        genre="pop punk",
        instruments=["crunchy guitar", "fast drums", "punchy bass"],
        bpm=(150, 175),
        mood=["restless", "bright"],
        mood_alternates=["urgent", "giddy"],
        instrument_alternates=["chugging guitar"],
        when=GenreWhen(class_min_share={"actioncam": 0.6}, energy=["high"]),
    ),
    GenreRow(
        name="reggae and dub",
        genre="reggae dub",
        instruments=["skanking guitar", "deep dub bass", "loose drums"],
        bpm=(70, 90),
        mood=["hazy", "unhurried"],
        mood_alternates=["drowsy", "warm"],
        instrument_alternates=["spring reverb guitar"],
        when=GenreWhen(tags_dominant=["beach"], energy=["low"]),
    ),
    GenreRow(
        name="funk and disco",
        genre="funk disco",
        instruments=["wah guitar", "slap bass", "tight drums"],
        bpm=(110, 125),
        mood=["joyful", "strutting"],
        mood_alternates=["giddy", "glittering"],
        instrument_alternates=["funky clavinet"],
        when=GenreWhen(tags_dominant=["people", "food"], energy=["high"]),
    ),
    GenreRow(
        name="acoustic and ukulele pop",
        genre="acoustic pop",
        instruments=["warm ukulele", "brushed drums", "soft acoustic guitar"],
        bpm=(95, 115),
        mood=["tender", "domestic"],
        mood_alternates=["gentle", "nostalgic"],
        instrument_alternates=["muted upright bass"],
        when=GenreWhen(tags_dominant=["people", "food"], energy=["low", "mid"]),
    ),
    GenreRow(
        name="italian and mediterranean folk",
        genre="mediterranean folk",
        instruments=["nylon string guitar", "hand percussion", "wheezing accordion"],
        bpm=(100, 120),
        mood=["sunlit", "convivial"],
        mood_alternates=["languid", "festive"],
        instrument_alternates=["bright mandolin"],
        when=GenreWhen(
            tags_dominant=["city", "street"],
            region_any=["sardegna", "sardinia", "italia", "italy"],
        ),
    ),
    GenreRow(
        name="americana",
        genre="americana",
        instruments=["slide guitar", "loping drums", "upright bass"],
        bpm=(95, 115),
        mood=["wide", "wistful"],
        mood_alternates=["dusty", "hopeful"],
        instrument_alternates=["weeping pedal steel"],
        when=GenreWhen(class_min_share={"drone": 0.5}, energy=["mid"]),
    ),
    GenreRow(
        name="cinematic ambient and post-rock",
        genre="cinematic post-rock",
        instruments=["sweeping strings", "soft piano", "swelling guitar"],
        bpm=(75, 95),
        mood=["vast", "still"],
        mood_alternates=["solemn", "weightless"],
        instrument_alternates=["bowed guitar"],
        when=GenreWhen(class_min_share={"drone": 0.5}, energy=["low"]),
    ),
    GenreRow(
        name="country",
        genre="country",
        instruments=["twangy guitar", "shuffling drums", "walking bass"],
        bpm=(100, 120),
        mood=["easygoing", "open"],
        mood_alternates=["homespun", "rolling"],
        instrument_alternates=["sawing fiddle"],
        when=GenreWhen(tags_dominant=["mountain", "street"], energy=["mid"]),
    ),
    GenreRow(
        name="rock",
        genre="rock",
        instruments=["distorted guitar", "heavy drums", "driving bass"],
        bpm=(120, 145),
        mood=["bold", "propulsive"],
        mood_alternates=["gritty", "elated"],
        instrument_alternates=["overdriven guitar"],
        when=GenreWhen(energy=["high"]),
    ),
    GenreRow(
        name="indie pop",
        genre="indie pop",
        instruments=["chiming guitar", "crisp drums", "round bass"],
        bpm=(105, 125),
        mood=["bright", "wandering"],
        mood_alternates=["dreamy", "buoyant"],
        instrument_alternates=["twinkling glockenspiel"],
        when=GenreWhen(energy=["mid"]),
    ),
    GenreRow(
        name="upbeat folk",
        genre="upbeat folk",
        instruments=["strummed acoustic guitar", "stomping percussion", "warm bass"],
        bpm=(100, 120),
        mood=["cheerful", "easy"],
        mood_alternates=["sunny", "companionable"],
        instrument_alternates=["rolling banjo"],
    ),
)

#: The section words Suno accepts. In configuration because the rules are Suno's and
#: they change without asking us.
DEFAULT_ALLOWED_SECTIONS: tuple[str, ...] = (
    "intro",
    "verse",
    "verse 1",
    "verse 2",
    "verse 3",
    "pre-chorus",
    "chorus",
    "bridge",
    "solo",
    "break",
    "drop",
    "build",
    "transition",
    "outro",
    "end",
)


class TimeOfDayBands(_Strict):
    """Hour ranges, local time, half open. Anything outside them is night."""

    morning: tuple[int, int] = (5, 9)
    daytime: tuple[int, int] = (9, 17)
    evening: tuple[int, int] = (17, 21)


class SoundtrackConfig(_Strict):
    variants: int = Field(default=3, ge=1, le=5)
    bpm_tolerance: float = 3.0
    beat_multiples: list[int] = Field(
        default_factory=lambda: [2, 4, 6, 8, 12, 16],
        description="A clip length is on the grid when it is this many beats long: half "
        "a bar to four bars at 4/4. The first version stopped at 8, which left a 6 s "
        "hero clip four beats from anything legal at any sane tempo. Measured on the "
        "Sardinia edit, adding 6, 12 and 16 took the mean distance from a whole beat "
        "from 0.705 to 0.419 beats and the worst case from 4.000 to 0.994.",
    )
    alternate_durations: bool = True
    refine: bool = Field(
        default=True,
        description="Ask the text model to polish the template prompt when cloud is "
        "enabled. The validator still decides, so a refusal costs one request.",
    )
    description_max_chars: int = Field(default=200, ge=40)
    allowed_sections: list[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_SECTIONS))
    energy_bands: tuple[float, float] = Field(
        default=(0.34, 0.67),
        description="Where the normalized energy curve turns from low to mid and from mid to high.",
    )
    time_of_day: TimeOfDayBands = TimeOfDayBands()
    default_profile: str = Field(
        default="upbeat folk",
        description="The row used when no row's conditions match. Named rather than "
        "positional so reordering the table cannot change the fallback by accident.",
    )
    genres: list[GenreRow] = Field(default_factory=lambda: list(DEFAULT_GENRE_ROWS))
    calm_to_energetic: list[str] = Field(
        default_factory=lambda: list(DEFAULT_CALM_TO_ENERGETIC),
        description="Mood words in order from calm to energetic, used by the GUI's mood "
        "control to choose between the words a row already offers. A word that is not "
        "listed counts as neutral rather than being guessed at.",
    )
    intimate_to_cinematic: list[str] = Field(
        default_factory=lambda: list(DEFAULT_INTIMATE_TO_CINEMATIC),
        description="The same words in order from intimate to cinematic, meaning how "
        "much room the music implies.",
    )


#: Mood words the shipped rows use, ordered from calm to energetic. A word absent from
#: this list sits in the middle: the two axes are a way of picking between the words a
#: row already offers, not a claim to understand any word in English.
DEFAULT_CALM_TO_ENERGETIC: tuple[str, ...] = (
    "still",
    "solemn",
    "drowsy",
    "languid",
    "unhurried",
    "tender",
    "gentle",
    "hazy",
    "dreamy",
    "wistful",
    "nostalgic",
    "weightless",
    "easy",
    "easygoing",
    "warm",
    "homespun",
    "domestic",
    "companionable",
    "wandering",
    "open",
    "hopeful",
    "breezy",
    "sunlit",
    "dusty",
    "carefree",
    "cheerful",
    "sunny",
    "bright",
    "playful",
    "buoyant",
    "rolling",
    "glittering",
    "joyful",
    "elated",
    "convivial",
    "festive",
    "bold",
    "strutting",
    "gritty",
    "giddy",
    "propulsive",
    "restless",
    "urgent",
    # "wide" and "vast" say how much room, not how much energy; they sit at the calm
    # end because the rows that use them are the slow ones.
    "wide",
    "vast",
)

#: The same words ordered from intimate to cinematic: how much room the music implies.
DEFAULT_INTIMATE_TO_CINEMATIC: tuple[str, ...] = (
    "domestic",
    "homespun",
    "companionable",
    "tender",
    "gentle",
    "still",
    "warm",
    "easy",
    "easygoing",
    "playful",
    "giddy",
    "cheerful",
    "carefree",
    "gritty",
    "strutting",
    "convivial",
    "festive",
    "restless",
    "urgent",
    "propulsive",
    "bright",
    "buoyant",
    "sunny",
    "sunlit",
    "dusty",
    "breezy",
    "rolling",
    "glittering",
    "joyful",
    "elated",
    "nostalgic",
    "wistful",
    "hazy",
    "drowsy",
    "languid",
    "unhurried",
    "dreamy",
    "wandering",
    "hopeful",
    "open",
    "solemn",
    "weightless",
    "bold",
    "wide",
    "vast",
)


class PlacesConfig(_Strict):
    geocode: bool = Field(
        default=True,
        description="Reverse geocode place centroids through Nominatim, once each and "
        "cached forever. False keeps places numeric and makes the run fully offline.",
    )
    user_agent: str | None = Field(
        default=None,
        description="Overrides the default 'autocut/<version>'. Nominatim requires a "
        "real one and blocks anonymous clients.",
    )
    min_interval_s: float = Field(
        default=1.0, ge=0.0, description="Nominatim's usage policy asks for one request a second."
    )


class ExportConfig(_Strict):
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

    @field_validator("lut", mode="before")
    @classmethod
    def _empty_lut_is_none(cls, value: object) -> object:
        """An empty string in the LUT table means no LUT for that class.

        TOML has no null and every key of a per class table has to be present, so a
        writer saying "this class has no LUT" has only the empty string to say it with.
        Read here rather than worked around at each call site, so a file written by the
        GUI and one written by hand mean the same thing.
        """
        if isinstance(value, dict):
            return {key: (None if item == "" else item) for key, item in value.items()}
        return value

    lens_correction: PerClass[bool] = PerClass(
        drone=False, actioncam=False, phone=False, reflex=False, generic=False
    )
    keep_rejects: bool = False
    workers: int | None = Field(
        default=None,
        ge=1,
        description="Thread pool size for encoding clips. Defaults to "
        "max(1, (analysis.workers or physical cores) // 2).",
    )
    uniform_frame: bool = Field(
        default=False,
        description="Scale and pad every selected clip onto one common frame, the "
        "smallest of their fitted sizes, so nothing is upscaled and every output has "
        "the same geometry. Off by default because a folder bound for CapCut does not "
        "need it; a render turns it on for the export it runs, because clips of "
        "different sizes cannot be joined without re-encoding.",
    )


class RenderConfig(_Strict):
    """The optional finished file: the exported clips joined with the track.

    Off by default. SPEC.md section 2 keeps editing out of AutoCut, and this is the one
    exception the user asked for: an edit whose clips, order and lengths are already
    decided needs nothing from CapCut but the export, so the render saves the round
    trip. Hard cuts only; anything that needs a transition still belongs in an editor.
    """

    enabled: bool = Field(
        default=False,
        description="Whether an export also writes the joined file. Off, because the "
        "normal path ends in CapCut and a render nobody asked for is a minute of disk "
        "and time for a file they will not open.",
    )
    fade_out_seconds: float = Field(
        default=1.5,
        ge=0.0,
        le=30.0,
        description="How long the track fades at the end of the edit. Short by "
        "default: a long fade over a musical peak is worse than a clean stop.",
    )
    filename: str = Field(
        default="montage.mp4",
        description="Name of the rendered file, written beside _selects/.",
    )
    audio_bitrate: str = Field(
        default="192k",
        description="AAC bitrate for the muxed track. Higher than the preview's, "
        "because this file is the one that gets watched.",
    )


DescribeScope = Literal["candidates", "selected"]


class ProvidersConfig(_Strict):
    cloud: bool = True
    vision_model: str = "google/gemini-2.5-flash"
    llm_model: str = "google/gemini-2.5-flash"
    # Bounded so a mistyped autocut.toml fails when it is loaded rather than when the
    # first request goes out, and so no value can ask for a thread per segment or for a
    # retry loop that outlives the user's patience.
    max_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Requests in flight. The work is network bound and the frames are "
        "already on disk, so a small thread pool is enough.",
    )
    max_retries: int = Field(
        default=4,
        ge=0,
        le=10,
        description="Retries per request on 429 and 5xx, with backoff 1, 2, 4, 8 s. "
        "Other 4xx fail immediately: a bad request does not get better.",
    )
    max_failures: int = Field(
        default=8,
        ge=1,
        le=1000,
        description="Consecutive failures that stop the run from issuing new requests. "
        "The rule against retrying into an outage forever that ADR 4 asks for.",
    )
    prompt_version: int = Field(
        default=1,
        ge=1,
        description="Bump this when the prompt wording changes. Cached responses are "
        "keyed by it, so a new version invalidates them on purpose.",
    )
    describe_scope: DescribeScope = Field(
        default="candidates",
        description="Which segments to describe. 'candidates' is about 60 on a holiday "
        "folder and costs a few cents; 'selected' is for large projects where only the "
        "final clips need a caption for the soundtrack prompt.",
    )
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


class GuiConfig(_Strict):
    """Settings the window needs and the command line has no use for.

    In the core's configuration rather than in the GUI package because every tunable
    lives here (AGENTS.md), and because a user who finds the sliders sluggish should be
    able to change the debounce in the same file as everything else.
    """

    slider_debounce_ms: int = Field(
        default=250,
        ge=0,
        le=5000,
        description="How long a slider has to stop moving before the edit is redone. "
        "Long enough that a drag is one re-selection rather than forty, short enough "
        "that the answer feels like it belongs to the gesture.",
    )
    reselect_worker_threshold: int = Field(
        default=300,
        ge=0,
        description="Candidate count above which a re-selection goes to the worker "
        "thread instead of running inline. Selection reads only cached arrays and "
        "takes well under a second on a normal holiday folder, so threading it always "
        "would cost more in complexity than it saves; a folder large enough to be felt "
        "gets the thread.",
    )
    grid_thumbnail_px: int = Field(
        default=196, ge=64, le=512, description="Card width in the review grid."
    )
    montage_height: int = Field(
        default=360,
        ge=144,
        le=1080,
        description="Height of the montage preview. Low on purpose: the montage exists "
        "to judge the sequence and the cuts, and a 4K one would take longer to build "
        "than the export it is meant to come before.",
    )
    montage_preset: str = Field(
        default="ultrafast",
        description="x264 preset for the montage parts. Speed over size: the file is "
        "watched once and rebuilt whenever the edit changes.",
    )
    montage_crf: int = Field(
        default=28,
        ge=0,
        le=51,
        description="Quality of the montage parts. Lower than the export's on purpose.",
    )
    min_window_width: int = Field(
        default=1100,
        ge=800,
        le=3840,
        description="Narrowest the window may be dragged. Every row of controls has to "
        "wrap or scroll above this, because Qt refuses to shrink a window under its "
        "layout's minimum and the user is then stuck with whatever the layout asked for.",
    )
    min_window_height: int = Field(
        default=680,
        ge=500,
        le=2160,
        description="Shortest the window may be dragged. 680 leaves a 720p laptop its "
        "menu bar and dock.",
    )
    panel_min_width: int = Field(
        default=280,
        ge=200,
        le=1200,
        description="Narrowest the Review right panel may be dragged. Under this the "
        "preview is too small to judge a frame and the weight rows stop lining up.",
    )
    rail_collapsed_width: int = Field(
        default=56,
        ge=40,
        le=120,
        description="Width of the navigation rail once collapsed to icons. Wide enough "
        "for a 16 px icon with room around it to be a target.",
    )
    panel_collapse_width: int = Field(
        default=1280,
        ge=800,
        le=3840,
        description="Window width under which the Review screen starts with its right "
        "panel collapsed, so the grid keeps the width on a small display.",
    )
    close_wait_ms: int = Field(
        default=5000,
        ge=0,
        le=120_000,
        description="How long closing a project waits for a cancelled stage to stop "
        "before giving up without saving. The cancel is seen between files, so a stage "
        "in the middle of an encode can outlast it; the window then stays open and "
        "closes itself when the stage ends, rather than freezing or saving a manifest "
        "the worker is still writing.",
    )
    theme: Literal["dark", "light", "system"] = Field(
        default="dark",
        description="Which token set the window is drawn with. Dark by default because "
        "that is the design that was approved and because footage reads better against "
        "it; 'system' picks one from the desktop palette at start up. Applied when the "
        "window opens, so a change takes effect on the next start (ADR 10).",
    )


class CacheConfig(_Strict):
    dir: Path | None = Field(default=None, description="Defaults to the platform cache dir.")
    models_dir: Path | None = Field(
        default=None,
        description="Where model weights live. Deliberately independent of 'dir': the "
        "analysis cache is per project by nature and a user may point it at a scratch "
        "disk, while a 350 MB checkpoint belongs to the machine and must not be "
        "downloaded again for every project. Defaults to the platform cache dir.",
    )
    memory_entries: int = Field(
        default=256,
        ge=0,
        description="Recently read analysis cache entries kept in memory, read-only, "
        "across re-selections. 0 disables the in-memory cache and reads every entry "
        "from disk on every selection.",
    )


class TimeoutsConfig(_Strict):
    """How long AutoCut waits for one external tool call before giving up on it."""

    ffprobe_s: float = Field(
        default=60.0, gt=0, description="One ffprobe call: a file, or an exported clip."
    )
    hwaccel_probe_s: float = Field(
        default=20.0,
        gt=0,
        description="Listing ffmpeg's compiled-in hardware decoders, or verifying one "
        "against a real file.",
    )
    sample_read_s: float = Field(
        default=900.0,
        gt=0,
        description="Reading the sampled frames ffmpeg writes to a pipe during analysis.",
    )
    export_clip_s: float = Field(default=1800.0, gt=0, description="Encoding one exported clip.")
    montage_part_s: float = Field(
        default=300.0, gt=0, description="Encoding one clip of the review montage."
    )
    concat_s: float = Field(
        default=600.0,
        gt=0,
        description="Joining already-encoded clips into a render or a montage.",
    )
    audio_decode_s: float = Field(
        default=300.0, gt=0, description="Decoding the soundtrack for beat sync."
    )
    telemetry_extract_s: float = Field(
        default=60.0, gt=0, description="Extracting an embedded telemetry subtitle track."
    )
    version_check_s: float = Field(
        default=10.0, gt=0, description="Reading one external tool's version, for `autocut doctor`."
    )


class AutocutConfig(_Strict):
    """Root configuration model."""

    analysis: AnalysisConfig = AnalysisConfig()
    weights: ScoringWeights = ScoringWeights()
    rules: RejectionRules = RejectionRules()
    selection: SelectionConfig = SelectionConfig()
    similarity: SimilarityConfig = SimilarityConfig()
    tags: TagsConfig = TagsConfig()
    soundtrack: SoundtrackConfig = SoundtrackConfig()
    export: ExportConfig = ExportConfig()
    render: RenderConfig = RenderConfig()
    providers: ProvidersConfig = ProvidersConfig()
    places: PlacesConfig = PlacesConfig()
    gui: GuiConfig = GuiConfig()
    cache: CacheConfig = CacheConfig()
    timeouts: TimeoutsConfig = TimeoutsConfig()

    @classmethod
    def load(cls, path: Path | None) -> AutocutConfig:
        """Load ``autocut.toml`` or return defaults when ``path`` is ``None`` or missing."""
        if path is None or not path.exists():
            return cls()
        with path.open("rb") as fh:
            return cls.model_validate(tomllib.load(fh))

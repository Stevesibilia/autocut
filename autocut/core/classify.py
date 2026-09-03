"""Capability based source classification (ADR 3).

The class is a pure function of the probe result, the telemetry kind, the path
relative to its source folder and the user overrides. No brand table drives
control flow: brand knowledge lives in the string tables below and in
``autocut.toml``, and an unknown device degrades to ``generic`` with image
metrics only.

The deciding signal travels with the class so the review report can explain a
misclassification and the user can override it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePath, PurePosixPath

from autocut.core.config import ClassOverride, SourceClass
from autocut.core.manifest import TelemetryKind
from autocut.core.probe import ANDROID_MAKE_KEY, APPLE_MAKE_KEY, ProbeResult

# Telemetry kinds that identify the aircraft or the camera on their own.
TELEMETRY_CLASSES: dict[TelemetryKind, SourceClass] = {
    "dji_embedded_srt": "drone",
    "dji_sidecar_srt": "drone",
    "gopro_gpmf": "actioncam",
}

ACTIONCAM_MARKERS = ("osmoaction", "gopro", "insta360", "hero")
CAMERA_MAKERS = ("fujifilm", "sony", "canon", "nikon", "panasonic", "olympus", "leica")
PHONE_MAKE_KEYS = (ANDROID_MAKE_KEY, APPLE_MAKE_KEY)

# Weakest signal, used only when nothing above decided.
FILENAME_PATTERNS: tuple[tuple[str, SourceClass], ...] = (
    ("GX", "actioncam"),
    ("GH", "actioncam"),
    ("GOPR", "actioncam"),
    ("DJI_", "drone"),
    ("IMG_", "phone"),
    ("VID_", "phone"),
    ("PXL_", "phone"),
    ("DSC", "reflex"),
)

# A frame rate this high only comes from a camera built for slow motion.
HIGH_FPS_THRESHOLD = 100.0


@dataclass(slots=True)
class Classification:
    """The class assigned to a file and why."""

    source_class: SourceClass
    signal: str
    overridden: bool = False


def classify(
    probe: ProbeResult,
    telemetry_kind: TelemetryKind,
    rel_path: PurePath,
    overrides: list[ClassOverride] | None = None,
) -> Classification:
    """Derive the source class. Overrides run last and win."""
    override = _match_override(rel_path, overrides or [])
    if override is not None:
        return Classification(override.source_class, "override", overridden=True)

    telemetry_class = TELEMETRY_CLASSES.get(telemetry_kind)
    if telemetry_class is not None:
        return Classification(telemetry_class, "telemetry")

    tag_text = " ".join(
        value for value in (probe.make, probe.model, probe.encoder) if value
    ).lower()
    if any(marker in tag_text for marker in ACTIONCAM_MARKERS):
        return Classification("actioncam", "make_tag")

    lowered_keys = {key.lower() for key in probe.format_tags}
    if any(key in lowered_keys for key in PHONE_MAKE_KEYS):
        return Classification("phone", "manufacturer_tag")

    if probe.make and any(maker in probe.make.lower() for maker in CAMERA_MAKERS):
        return Classification("reflex", "make_tag")

    if probe.is_vertical and probe.width > 0:
        return Classification("phone", "aspect")

    if probe.fps >= HIGH_FPS_THRESHOLD:
        return Classification("actioncam", "fps")

    name = rel_path.name.upper()
    for prefix, source_class in FILENAME_PATTERNS:
        if name.startswith(prefix):
            return Classification(source_class, "filename")

    return Classification("generic", "default")


def _match_override(rel_path: PurePath, overrides: list[ClassOverride]) -> ClassOverride | None:
    """Last matching glob wins. Matching is case sensitive on the posix form."""
    text = PurePosixPath(*rel_path.parts).as_posix() if rel_path.parts else ""
    winner: ClassOverride | None = None
    for override in overrides:
        # fnmatch wildcards cross directory separators, so "GoPro/**" and
        # "GoPro/*" both match at any depth below the folder.
        if fnmatchcase(text, override.glob):
            winner = override
    return winner

"""Source classification: every scenario in specs/source-classification."""

from __future__ import annotations

from pathlib import Path, PurePath

from autocut.core.classify import classify
from autocut.core.config import ClassOverride
from autocut.core.manifest import TelemetryKind
from autocut.core.probe import ProbeResult


def probe(**fields: object) -> ProbeResult:
    defaults: dict[str, object] = {
        "path": Path("clip.mp4"),
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "codec": "h264",
        "pix_fmt": "yuv420p",
    }
    defaults.update(fields)
    return ProbeResult.model_validate(defaults)


def assign(
    result: ProbeResult,
    telemetry: TelemetryKind = "none",
    name: str = "clip.mp4",
    overrides: list[ClassOverride] | None = None,
) -> tuple[str, str, bool]:
    classification = classify(result, telemetry, PurePath(name), overrides)
    return classification.source_class, classification.signal, classification.overridden


def test_dji_mini2_is_a_drone_from_telemetry_alone() -> None:
    assert assign(probe(), telemetry="dji_embedded_srt", name="DJI_0744.MP4") == (
        "drone",
        "telemetry",
        False,
    )


def test_sidecar_telemetry_is_also_a_drone() -> None:
    assert assign(probe(), telemetry="dji_sidecar_srt")[0] == "drone"


def test_osmo_action4_from_the_encoder_tag() -> None:
    assert assign(probe(encoder="DJI OsmoAction4", fps=50.0), name="DJI_0194_D.MP4") == (
        "actioncam",
        "make_tag",
        False,
    )


def test_gopro_from_the_model_tag() -> None:
    assert assign(probe(model="HERO12 Black"))[0] == "actioncam"


def test_xiaomi_phone_from_the_android_manufacturer_tag() -> None:
    result = probe(
        make="Xiaomi",
        model="2312DRA50G",
        format_tags={"com.android.manufacturer": "Xiaomi", "com.android.model": "2312DRA50G"},
    )
    assert assign(result, name="VID_20250720_211104.mp4") == ("phone", "manufacturer_tag", False)


def test_apple_phone_from_the_quicktime_make_tag() -> None:
    result = probe(format_tags={"com.apple.quicktime.make": "Apple"}, make="Apple")
    assert assign(result, name="IMG_0001.MOV")[0] == "phone"


def test_camera_maker_is_a_reflex() -> None:
    assert assign(probe(make="FUJIFILM", format_tags={"make": "FUJIFILM"}))[0] == "reflex"


def test_unknown_camera_is_generic() -> None:
    assert assign(probe(), name="clip0001.mp4") == ("generic", "default", False)


def test_filename_is_only_a_weak_hint() -> None:
    """A make tag beats the VID_ prefix that would otherwise say phone."""
    result = probe(make="FUJIFILM", format_tags={"make": "FUJIFILM"})
    assert assign(result, name="VID_0001.mp4") == ("reflex", "make_tag", False)


def test_filename_decides_when_nothing_else_does() -> None:
    assert assign(probe(), name="GX010001.MP4") == ("actioncam", "filename", False)
    assert assign(probe(), name="DSC_0001.MOV") == ("reflex", "filename", False)


def test_vertical_orientation_hints_at_a_phone() -> None:
    assert assign(probe(rotation=-90), name="clip.mp4") == ("phone", "aspect", False)


def test_very_high_frame_rate_hints_at_an_actioncam() -> None:
    assert assign(probe(fps=240.0), name="clip.mp4") == ("actioncam", "fps", False)


def test_folder_override_wins_over_every_signal() -> None:
    overrides = [ClassOverride(glob="GoPro/**", source_class="actioncam")]
    result = probe(make="FUJIFILM", format_tags={"make": "FUJIFILM"})
    assert assign(result, name="GoPro/GX010001.MP4", overrides=overrides) == (
        "actioncam",
        "override",
        True,
    )


def test_last_matching_override_wins() -> None:
    overrides = [
        ClassOverride(glob="trip/**", source_class="phone"),
        ClassOverride(glob="trip/drone/**", source_class="drone"),
    ]
    assert assign(probe(), name="trip/drone/A.MP4", overrides=overrides)[0] == "drone"
    assert assign(probe(), name="trip/other/B.MP4", overrides=overrides)[0] == "phone"


def test_override_that_does_not_match_leaves_the_derived_class() -> None:
    overrides = [ClassOverride(glob="GoPro/**", source_class="actioncam")]
    assert assign(probe(), telemetry="dji_embedded_srt", overrides=overrides) == (
        "drone",
        "telemetry",
        False,
    )

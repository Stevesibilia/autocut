"""Export plans and the ffmpeg argument lists they produce.

Nothing here runs ffmpeg. The command is a pure function of a plan, which is the
whole reason it is built as one: the filter chain is the part that is easy to get
wrong and expensive to check by encoding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.ffmpeg_cmd import (
    ExportOverrides,
    ExportPlan,
    build_export_command,
    dominant_fps,
    filter_chain,
    fit_inside,
    is_fps_converted,
    plan_export,
    quality_flags,
    reaches,
    resolve_target_fps,
)
from autocut.core.manifest import Manifest, Segment, SourceFile

DAY = datetime(2025, 7, 14, 13, 0, tzinfo=UTC)


def project(tmp_path: Path) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(created_at=now, updated_at=now, sources=[Path("/f")], output_dir=tmp_path)


def source(
    file_id: str = "a",
    source_class: str = "drone",
    width: int = 3840,
    height: int = 2160,
    fps: float = 25.0,
    rotation: int = 0,
    pix_fmt: str = "yuv420p",
    bit_depth: int = 8,
    duration_s: float = 30.0,
) -> SourceFile:
    return SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=duration_s,
        width=width,
        height=height,
        rotation=rotation,
        fps=fps,
        codec="h264",
        pix_fmt=pix_fmt,
        bit_depth=bit_depth,
        creation_time=DAY,
    )


def segment(
    segment_id: str = "a:0",
    file_id: str = "a",
    center: float = 10.0,
    duration: float = 3.0,
    outcome: str = "selected",
    order: int | None = 1,
) -> Segment:
    return Segment(
        id=segment_id,
        file_id=file_id,
        start_s=5.0,
        end_s=20.0,
        trimmed_start_s=6.0,
        trimmed_end_s=19.0,
        best_center_s=center,
        target_duration_s=duration,
        outcome=outcome,  # type: ignore[arg-type]
        order=order,
    )


def planned(
    tmp_path: Path,
    src: SourceFile,
    seg: Segment | None = None,
    config: AutocutConfig | None = None,
    overrides: ExportOverrides | None = None,
    target_fps: float | None = None,
) -> ExportPlan:
    """One clip's plan.

    ``target_fps`` is recorded on the manifest because the target is a property of
    the whole selection: a project holding only one 50 fps clip would otherwise
    export at 50 and never reach slow motion.
    """
    manifest = project(tmp_path)
    seg = seg or segment(file_id=src.id)
    manifest.files[src.id] = src
    manifest.segments[seg.id] = seg
    if target_fps is not None:
        manifest.export.target_fps = target_fps
    return plan_export(
        seg,
        src,
        manifest,
        config or AutocutConfig(),
        overrides,
        output=tmp_path / "001_20250714_drone_clip_3.0s.mp4",
    )


def argument_after(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


# --- geometry and frame rate helpers -----------------------------------------


def test_fit_inside_never_upscales() -> None:
    assert fit_inside(1920, 1080, 3840, 2160) == (1920, 1080)


def test_fit_inside_downscales_and_keeps_the_aspect() -> None:
    assert fit_inside(3840, 2160, 1920, 1080) == (1920, 1080)


def test_fit_inside_returns_even_dimensions() -> None:
    width, height = fit_inside(1001, 667, 500, 500)
    assert width % 2 == 0 and height % 2 == 0


def test_fit_inside_on_an_unknown_size() -> None:
    assert fit_inside(0, 0, 3840, 2160) == (0, 0)


@pytest.mark.parametrize(
    ("source_fps", "target", "converted"),
    [
        (25.0, 25.0, False),
        (50.0, 25.0, False),
        (30.0, 25.0, True),
        (29.97, 25.0, True),
        (29.97, 30.0, False),
        (25.0, 50.0, True),
        (0.0, 25.0, False),
    ],
)
def test_fps_conversion_is_flagged_only_when_frames_are_resampled(
    source_fps: float, target: float, converted: bool
) -> None:
    assert is_fps_converted(source_fps, target) is converted


def selection(tmp_path: Path, *groups: tuple[int, float]) -> Manifest:
    """A manifest whose selected clips have the given counts at the given frame rates."""
    manifest = project(tmp_path)
    for index, (count, fps) in enumerate(groups):
        for number in range(count):
            file_id = f"f{index}_{number}"
            manifest.files[file_id] = source(file_id, fps=fps)
            manifest.segments[f"{file_id}:0"] = segment(f"{file_id}:0", file_id)
    return manifest


def test_auto_picks_the_rate_the_most_clips_divide_into(tmp_path: Path) -> None:
    """The Sardinia mix in specs/clip-export: 24 at 50, 14 at 25 and 2 at 30 gives 25.

    The mode is 50 and only those 24 clips reach it. 38 reach 25, by taking every
    other frame of the 50 fps clips and every frame of the 25 fps ones.
    """
    manifest = selection(tmp_path, (24, 50.0), (14, 25.0), (2, 30.0))
    assert dominant_fps(manifest) == 25.0


def test_one_frame_rate_everywhere_is_the_target(tmp_path: Path) -> None:
    assert dominant_fps(selection(tmp_path, (12, 30.0))) == 30.0


def test_two_rates_that_do_not_divide_into_each_other(tmp_path: Path) -> None:
    """Neither 24 nor 30 reaches the other, so the larger group wins."""
    assert dominant_fps(selection(tmp_path, (12, 24.0), (8, 30.0))) == 24.0
    assert dominant_fps(selection(tmp_path, (8, 24.0), (12, 30.0))) == 30.0


def test_a_tie_goes_to_the_lowest_rate(tmp_path: Path) -> None:
    assert dominant_fps(selection(tmp_path, (10, 24.0), (10, 30.0))) == 24.0
    # Insertion order must not decide it either.
    assert dominant_fps(selection(tmp_path, (10, 30.0), (10, 24.0))) == 24.0


def test_a_rate_nothing_else_reaches_does_not_win_on_count(tmp_path: Path) -> None:
    """50 has the most clips; 25 has the most reach, which is what the rule counts."""
    assert dominant_fps(selection(tmp_path, (6, 50.0), (5, 25.0))) == 25.0


def test_the_real_frame_rates_of_the_sardinia_set(tmp_path: Path) -> None:
    """The phone files probe at 30.033, not a round 30, and must not reach 25."""
    manifest = selection(tmp_path, (24, 50.0), (14, 25.0), (2, 30.033))
    assert dominant_fps(manifest) == 25.0
    assert not reaches(30.033, 25.0)
    assert reaches(30.033, 30.033)


@pytest.mark.parametrize(
    ("source_fps", "target", "arrives"),
    [
        (25.0, 25.0, True),
        (50.0, 25.0, True),
        (100.0, 25.0, True),
        (30.0, 25.0, False),
        (29.97, 30.0, True),
        (25.0, 50.0, False),
        (0.0, 25.0, False),
    ],
)
def test_reaching_a_target_means_dropping_whole_frames(
    source_fps: float, target: float, arrives: bool
) -> None:
    assert reaches(source_fps, target) is arrives


def test_only_selected_clips_decide_the_target(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    manifest.files["a"] = source("a", fps=50.0)
    manifest.files["b"] = source("b", fps=30.0)
    manifest.segments["a:0"] = segment("a:0", "a", outcome="selected")
    manifest.segments["b:0"] = segment("b:0", "b", outcome="candidate")
    manifest.segments["b:1"] = segment("b:1", "b", outcome="rejected")
    assert dominant_fps(manifest) == 50.0


def test_a_project_with_nothing_selected_falls_back_to_25(tmp_path: Path) -> None:
    assert dominant_fps(project(tmp_path)) == 25.0


def test_an_explicit_fps_wins_over_everything(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    manifest.export.target_fps = 30.0
    config = AutocutConfig()
    config.export.fps = 50.0
    assert resolve_target_fps(manifest, config, ExportOverrides(fps=24.0)) == 24.0
    assert resolve_target_fps(manifest, config) == 50.0


def test_a_recorded_target_survives_a_changed_selection(tmp_path: Path) -> None:
    """Deselecting one clip must not flip the target and invalidate every output."""
    manifest = project(tmp_path)
    manifest.files["a"] = source("a", fps=50.0)
    manifest.segments["a:0"] = segment("a:0", "a")
    manifest.export.target_fps = 25.0
    assert resolve_target_fps(manifest, AutocutConfig()) == 25.0


# --- plans -------------------------------------------------------------------


def test_a_phone_clip_is_not_upscaled(tmp_path: Path) -> None:
    """The scenario in specs/clip-export: 1920x1080 under a 3840x2160 maximum."""
    plan = planned(tmp_path, source("p", "phone", width=1920, height=1080))
    assert plan.scale_w is None and plan.scale_h is None
    assert "scale=" not in filter_chain(plan)


def test_a_4k_clip_is_scaled_down_to_the_maximum(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.max_width, config.export.max_height = 1920, 1080
    plan = planned(tmp_path, source(), config=config)
    assert (plan.scale_w, plan.scale_h) == (1920, 1080)
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in filter_chain(plan)


def test_the_window_is_the_target_duration_around_the_center(tmp_path: Path) -> None:
    plan = planned(tmp_path, source(), segment(center=10.0, duration=3.0))
    assert plan.source_start_s == pytest.approx(8.5)
    assert plan.source_duration_s == pytest.approx(3.0)
    assert plan.out_duration_s == pytest.approx(3.0)
    assert plan.out_frames == 75


def test_the_window_stays_inside_the_file(tmp_path: Path) -> None:
    plan = planned(tmp_path, source(duration_s=10.0), segment(center=9.8, duration=3.0))
    assert plan.source_start_s == pytest.approx(7.0)
    assert plan.source_start_s + plan.source_duration_s <= 10.0 + 1e-9


def test_a_file_shorter_than_the_window_starts_at_zero(tmp_path: Path) -> None:
    plan = planned(tmp_path, source(duration_s=2.0), segment(center=1.0, duration=3.0))
    assert plan.source_start_s == 0.0


def test_a_segment_without_a_window_uses_its_midpoint(tmp_path: Path) -> None:
    seg = segment()
    seg.best_center_s = None
    plan = planned(tmp_path, source(), seg)
    # start_s 5.0 and end_s 20.0 put the midpoint at 12.5.
    assert plan.source_start_s == pytest.approx(11.0)


def test_slow_motion_halves_the_source_window(tmp_path: Path) -> None:
    """The scenario in specs/clip-export: 1.5 s of 50 fps source becomes 3.0 s at 25."""
    plan = planned(
        tmp_path, source("c", "actioncam", fps=50.0), segment(file_id="c"), target_fps=25.0
    )
    assert plan.slow_motion_ratio == 2
    assert plan.source_duration_s == pytest.approx(1.5)
    assert plan.out_duration_s == pytest.approx(3.0)
    assert plan.out_frames == 75


def test_slow_motion_is_off_for_a_class_that_did_not_ask_for_it(tmp_path: Path) -> None:
    plan = planned(tmp_path, source("d", "drone", fps=50.0), target_fps=25.0)
    assert plan.slow_motion_ratio == 1
    assert plan.source_duration_s == pytest.approx(3.0)


def test_slow_motion_needs_at_least_twice_the_target(tmp_path: Path) -> None:
    plan = planned(
        tmp_path, source("c", "actioncam", fps=30.0), segment(file_id="c"), target_fps=25.0
    )
    assert plan.slow_motion_ratio == 1


def test_every_class_is_silent_by_default(tmp_path: Path) -> None:
    """The scenario in specs/clip-export: the soundtrack carries the sound."""
    assert planned(tmp_path, source("d", "drone")).audio is False
    assert planned(tmp_path, source("p", "phone"), segment(file_id="p")).audio is False


def test_a_class_can_opt_back_into_its_ambience(tmp_path: Path) -> None:
    """The scenario in specs/clip-export: phone keeps its audio, drone still has none."""
    config = AutocutConfig()
    config.export.remove_audio.phone = False
    phone = planned(tmp_path, source("p", "phone"), segment(file_id="p"), config)
    drone = planned(tmp_path, source("d", "drone"), config=config)
    assert phone.audio is True
    assert drone.audio is False


def test_no_audio_silences_a_class_that_opted_in(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.remove_audio.phone = False
    silenced = planned(
        tmp_path,
        source("p", "phone"),
        segment(file_id="p"),
        config,
        overrides=ExportOverrides(no_audio=True),
    )
    assert silenced.audio is False


def test_slow_motion_drops_audio_even_when_the_class_keeps_it(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.remove_audio.actioncam = False
    plan = planned(
        tmp_path, source("c", "actioncam", fps=50.0), segment(file_id="c"), config, target_fps=25.0
    )
    assert plan.slow_motion
    assert plan.keep_audio is True
    assert plan.audio is False


def test_passthrough_leaves_the_pixel_format_alone(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.pix_fmt = "passthrough"
    plan = planned(tmp_path, source(), config=config)
    assert plan.pix_fmt is None
    assert "format=" not in filter_chain(plan)


def test_a_10_bit_source_is_converted_by_default(tmp_path: Path) -> None:
    """The scenario in specs/clip-export: yuv420p10le out with the default settings."""
    plan = planned(tmp_path, source(pix_fmt="yuv420p10le", bit_depth=10))
    assert plan.pix_fmt == "yuv420p"
    assert filter_chain(plan).endswith("format=yuv420p")
    assert "-pix_fmt" in build_export_command(plan)


# --- vertical strategies -----------------------------------------------------


def vertical_source(file_id: str = "v") -> SourceFile:
    """A phone clip stored landscape with rotation side data, like the Xiaomi files."""
    return source(file_id, "phone", width=1920, height=1080, rotation=-90)


def test_the_vertical_fixture_shape_is_read_from_rotation() -> None:
    src = vertical_source()
    assert src.is_vertical
    assert (src.display_width, src.display_height) == (1080, 1920)


def test_exclude_changes_nothing_in_the_command(tmp_path: Path) -> None:
    plan = planned(tmp_path, vertical_source(), segment(file_id="v"))
    chain = filter_chain(plan)
    assert "crop" not in chain and "overlay" not in chain


def test_center_crop_crops_to_the_target_aspect(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.vertical_strategy = "center_crop"
    plan = planned(tmp_path, vertical_source(), segment(file_id="v"), config)
    # 1080 wide at 16:9 is 607.5, rounded to the nearest even 608.
    assert plan.crop_w == 1080
    assert plan.crop_h == 608
    assert "crop=1080:608" in filter_chain(plan)


def test_blur_pad_puts_the_clip_on_a_target_aspect_canvas(tmp_path: Path) -> None:
    """The scenario in specs/clip-export: 1080x1920 on 16:9 with blurred sides."""
    config = AutocutConfig()
    config.export.vertical_strategy = "blur_pad"
    plan = planned(tmp_path, vertical_source(), segment(file_id="v"), config)
    assert plan.pad_h == 1920
    assert plan.pad_w == pytest.approx(round(1920 * 16 / 9), abs=2)
    chain = filter_chain(plan)
    assert "split[bg][fg]" in chain
    assert "boxblur" in chain
    assert "overlay=(W-w)/2:(H-h)/2" in chain
    assert plan.pad_w is not None and plan.pad_h is not None
    assert abs(plan.pad_w / plan.pad_h - 16 / 9) < 0.01


def test_blur_pad_stays_inside_the_configured_maximum(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.vertical_strategy = "blur_pad"
    config.export.max_width, config.export.max_height = 1280, 720
    plan = planned(tmp_path, vertical_source(), segment(file_id="v"), config)
    assert plan.pad_w is not None and plan.pad_h is not None
    assert plan.pad_w <= 1280 and plan.pad_h <= 720
    assert plan.scale_h is not None and plan.scale_h <= plan.pad_h


def test_a_horizontal_clip_ignores_the_vertical_strategy(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.vertical_strategy = "blur_pad"
    plan = planned(tmp_path, source(), config=config)
    assert plan.pad_w is None
    assert "overlay" not in filter_chain(plan)


# --- luts, lenses and encoders ----------------------------------------------


def test_a_lut_applies_to_its_class_only(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.lut.drone = Path("/luts/dlog.cube")
    drone = planned(tmp_path, source("d", "drone"), config=config)
    phone = planned(tmp_path, source("p", "phone"), segment(file_id="p"), config)
    assert "lut3d=file=/luts/dlog.cube" in filter_chain(drone)
    assert "lut3d" not in filter_chain(phone)


def test_a_lut_path_with_a_colon_is_escaped(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.lut.drone = Path("/luts/a:b.cube")
    chain = filter_chain(planned(tmp_path, source(), config=config))
    assert r"lut3d=file=/luts/a\:b.cube" in chain


def test_lens_correction_applies_to_its_class_only(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.lens_correction.actioncam = True
    action = planned(tmp_path, source("c", "actioncam"), segment(file_id="c"), config)
    drone = planned(tmp_path, source("d", "drone"), config=config)
    assert "lenscorrection=" in filter_chain(action)
    assert "lenscorrection" not in filter_chain(drone)


def test_the_filter_order_is_the_one_the_design_fixes(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.vertical_strategy = "center_crop"
    config.export.lut.phone = Path("/luts/p.cube")
    config.export.lens_correction.phone = True
    config.export.max_width, config.export.max_height = 720, 405
    plan = planned(tmp_path, vertical_source(), segment(file_id="v"), config)
    chain = filter_chain(plan)
    order = [
        chain.index(part)
        for part in ("fps=", "scale=", "crop=", "lut3d", "lenscorrection", "format=")
    ]
    assert order == sorted(order), chain


def test_slow_motion_restamps_before_the_frame_rate_filter(tmp_path: Path) -> None:
    plan = planned(
        tmp_path, source("c", "actioncam", fps=50.0), segment(file_id="c"), target_fps=25.0
    )
    chain = filter_chain(plan)
    assert chain.index("setpts=2*PTS") < chain.index("fps=25")


@pytest.mark.parametrize(
    ("codec", "expected"),
    [
        ("libx264", ["-crf", "18", "-preset", "medium"]),
        ("libx265", ["-crf", "18", "-preset", "medium"]),
        ("h264_vaapi", ["-qp", "18"]),
        ("h264_videotoolbox", ["-q:v", "65"]),
    ],
)
def test_each_encoder_gets_its_own_quality_flags(codec: str, expected: list[str]) -> None:
    assert quality_flags(codec, 18) == expected


def test_vaapi_uploads_to_the_gpu_instead_of_naming_a_pixel_format(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.codec = "h264_vaapi"
    plan = planned(tmp_path, source(), config=config)
    command = build_export_command(plan)
    assert filter_chain(plan).endswith("format=nv12,hwupload")
    assert "-vaapi_device" in command
    assert command.index("-vaapi_device") < command.index("-i")
    assert "-pix_fmt" not in command


# --- whole commands ----------------------------------------------------------


def test_a_precise_drone_command(tmp_path: Path) -> None:
    """The argument list scenario in specs/clip-export."""
    plan = planned(tmp_path, source("d", "drone"))
    command = build_export_command(plan)
    assert command[0] == "ffmpeg"
    assert "-ss" in command and command.index("-ss") < command.index("-i")
    assert argument_after(command, "-ss") == "8.500"
    assert argument_after(command, "-frames:v") == "75"
    assert "-an" in command
    chain = argument_after(command, "-vf")
    assert chain.startswith("fps=25")
    assert "-c:v" in command and argument_after(command, "-c:v") == "libx264"
    assert argument_after(command, "-crf") == "18"
    assert argument_after(command, "-pix_fmt") == "yuv420p"
    assert command[-1] == str(plan.output)
    # The DJI telemetry subtitle track must not be muxed into the clip.
    assert argument_after(command, "-map") == "0:v:0"
    assert "-sn" in command and "-dn" in command


def test_a_fast_phone_command_copies_and_keeps_audio(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.remove_audio.phone = False
    plan = planned(
        tmp_path,
        source("p", "phone", width=1920, height=1080),
        segment(file_id="p"),
        config,
        overrides=ExportOverrides(fast=True),
    )
    command = build_export_command(plan)
    assert plan.mode == "fast"
    assert "-c" in command and argument_after(command, "-c") == "copy"
    # A stream copy cannot filter, so nothing is normalized.
    assert "-vf" not in command
    assert "-an" not in command
    assert "0:a:0?" in command
    assert argument_after(command, "-t") == "3.000"


def test_a_slow_motion_action_cam_command(tmp_path: Path) -> None:
    plan = planned(
        tmp_path, source("c", "actioncam", fps=50.0), segment(file_id="c"), target_fps=25.0
    )
    command = build_export_command(plan)
    chain = argument_after(command, "-vf")
    assert chain.startswith("setpts=2*PTS,fps=25")
    assert argument_after(command, "-frames:v") == "75"
    assert "-an" in command


def test_a_blur_pad_command_is_one_filtergraph(tmp_path: Path) -> None:
    config = AutocutConfig()
    config.export.vertical_strategy = "blur_pad"
    plan = planned(tmp_path, vertical_source(), segment(file_id="v"), config)
    command = build_export_command(plan)
    chain = argument_after(command, "-vf")
    # One input and one output, so it still fits in -vf rather than needing
    # -filter_complex and an explicit -map of the result.
    assert chain.count("[fg]") == 2
    assert "-filter_complex" not in command


def test_the_output_directory_is_not_created_by_the_builder(tmp_path: Path) -> None:
    """Building a command must be free of side effects; the worker makes the folder."""
    plan = planned(tmp_path, source())
    build_export_command(plan)
    assert not (tmp_path / "001_20250714_drone_clip_3.0s.mp4").exists()

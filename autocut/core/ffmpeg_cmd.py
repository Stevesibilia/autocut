"""Build the ffmpeg argument list for one clip (ADR 2).

The whole command is a pure function of a plan, so the filter chain is unit tested
without spawning anything and reads the same on Linux and macOS. This module decides
what one clip's output should be and how to ask ffmpeg for it;
:mod:`autocut.core.export` decides which clips to run, in what order and what to skip.

Seeking is a plain accurate input seek to the window start. ``-ss`` before ``-i``
has been frame accurate since ffmpeg gained ``-accurate_seek`` as a default: it
seeks to the previous keyframe and decodes forward to the requested time. The older
idiom of seeking one second early and trimming the second back on the output side
was measured against it on a fixture whose only keyframe is at 0.0, and the two
produce the same duration to the microsecond and the same first frame to within
re-encode noise, so the simpler form is used.

Precise mode trims with ``-frames:v`` rather than ``-t``. A window rarely starts on a
source frame boundary, and ``-t`` then measures against the ``fps`` filter's own grid
and can stop a frame early: three seconds taken from 2.5 s of a 25 fps source measured
2.96. A frame count says the same thing in the unit the output is made of. Fast mode
keeps ``-t``, because a stream copy has no filter grid to align to and its bounds are
approximate by definition. When audio is kept the container can still run up to one
frame long, since an AAC frame is 21.3 ms and the last one is not split.

``-map`` is explicit. Left to itself ffmpeg picks one stream of each kind, which on
this footage means muxing the DJI telemetry subtitle track into the clip. The Action 4
also carries ``djmd`` and ``dbgi`` data streams and a timecode track, and an embedded
still image as a second video stream, so the first video stream is named rather than
implied and the muxer is told not to write a timecode track of its own.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from autocut.core.config import AutocutConfig, CutMode, ExportConfig, VerticalStrategy
from autocut.core.manifest import Manifest, Segment, SourceFile

# Highest CRF the scale is defined over, used to map a CRF onto the quality scales
# the hardware encoders use instead.
MAX_CRF = 51
VIDEOTOOLBOX_MAX_QUALITY = 100


@dataclass(frozen=True, slots=True)
class ExportPlan:
    """Everything one clip's command needs, already decided.

    ``source_duration_s`` is how much of the source is read and ``out_duration_s``
    how long the result lasts. They differ only under slow motion, where the ratio
    between them is ``slow_motion_ratio``.
    """

    source: Path
    output: Path
    source_start_s: float
    source_duration_s: float
    out_duration_s: float
    target_fps: float
    mode: CutMode = "precise"
    codec: str = "libx264"
    crf: int = 18
    pix_fmt: str | None = "yuv420p"
    keep_audio: bool = False
    scale_w: int | None = None
    scale_h: int | None = None
    slow_motion_ratio: int = 1
    vertical_strategy: VerticalStrategy = "exclude"
    is_vertical: bool = False
    pad_w: int | None = None
    pad_h: int | None = None
    blur_radius: int = 0
    crop_w: int | None = None
    crop_h: int | None = None
    lut: Path | None = None
    lens_correction: bool = False
    lens_k1: float = -0.2
    lens_k2: float = 0.0
    fps_converted: bool = False

    @property
    def slow_motion(self) -> bool:
        return self.slow_motion_ratio > 1

    @property
    def out_frames(self) -> int:
        """How many frames the output holds, which is what precise mode asks ffmpeg for."""
        return max(1, round(self.out_duration_s * self.target_fps))

    @property
    def audio(self) -> bool:
        """Whether the output carries an audio stream.

        Slow motion always drops it. The video is stretched by an integer ratio and
        the audio is not, so keeping it would leave a clip whose sound stops a third
        of the way through, and pitch shifted holiday audio is worse than silence.
        """
        return self.keep_audio and not self.slow_motion


def quality_flags(codec: str, crf: int) -> list[str]:
    """The rate control flags for ``codec``, expressed from one CRF number.

    Only the software encoders take a CRF. The hardware ones are opt-in and have
    their own scales, so the configured CRF is mapped onto them rather than asking
    the user to learn three quality scales.
    """
    if codec in ("libx264", "libx265"):
        return ["-crf", str(crf), "-preset", "medium"]
    if codec == "h264_vaapi":
        return ["-qp", str(crf)]
    if codec == "h264_videotoolbox":
        quality = round(VIDEOTOOLBOX_MAX_QUALITY * (1.0 - crf / MAX_CRF))
        return ["-q:v", str(max(1, min(VIDEOTOOLBOX_MAX_QUALITY, quality)))]
    return ["-crf", str(crf)]


def filter_chain(plan: ExportPlan) -> str:
    """The ``-vf`` graph, in the order the design fixes.

    Slow motion comes before the frame rate filter: ``setpts`` restamps the frames it
    is given and ``fps`` then resamples that stretched timeline onto the target grid,
    which yields real frames at a slower speed. The other way round would resample
    first and stretch the result, leaving the output at a fraction of the target rate.
    """
    parts: list[str] = []
    if plan.slow_motion:
        parts.append(f"setpts={plan.slow_motion_ratio}*PTS")
    parts.append(f"fps={plan.target_fps:g}")

    if plan.scale_w and plan.scale_h:
        parts.append(f"scale={plan.scale_w}:{plan.scale_h}:force_original_aspect_ratio=decrease")

    parts.extend(_vertical_filters(plan))

    if plan.lut is not None:
        # A Windows drive letter or a comma in the path would end the filter argument.
        parts.append(f"lut3d=file={_escape(str(plan.lut))}")
    if plan.lens_correction:
        parts.append(f"lenscorrection=k1={plan.lens_k1:g}:k2={plan.lens_k2:g}")

    parts.append(_pixel_format_tail(plan))
    return ",".join(part for part in parts if part)


def _vertical_filters(plan: ExportPlan) -> list[str]:
    """Nothing unless this clip is vertical and a strategy asks for a shape change."""
    if not plan.is_vertical:
        return []
    if plan.vertical_strategy == "center_crop" and plan.crop_w and plan.crop_h:
        return [f"crop={plan.crop_w}:{plan.crop_h}"]
    if plan.vertical_strategy == "blur_pad" and plan.pad_w and plan.pad_h:
        # One copy is blown up to cover the canvas and blurred into a backdrop, the
        # other is laid on top untouched. Labels keep it a single input, single
        # output graph, so it still fits in -vf.
        return [
            "split[bg][fg]",
            f"[bg]scale={plan.pad_w}:{plan.pad_h}:force_original_aspect_ratio=increase,"
            f"crop={plan.pad_w}:{plan.pad_h},"
            f"boxblur=luma_radius={plan.blur_radius}:luma_power=1:"
            f"chroma_radius={max(1, plan.blur_radius // 2)}:chroma_power=1[bgb]",
            "[bgb][fg]overlay=(W-w)/2:(H-h)/2",
        ]
    return []


def _pixel_format_tail(plan: ExportPlan) -> str:
    """The last filter, which is where the frames are handed to the encoder.

    VAAPI encodes from surfaces in GPU memory, so the chain ends by converting to
    ``nv12`` and uploading rather than by naming an output pixel format.
    """
    if plan.codec == "h264_vaapi":
        return "format=nv12,hwupload"
    if plan.pix_fmt is None:
        return ""
    return f"format={plan.pix_fmt}"


def _escape(value: str) -> str:
    """Escape a value that sits inside one filter argument."""
    return value.replace("\\", "\\\\").replace(":", r"\:").replace(",", r"\,")


def build_export_command(plan: ExportPlan) -> list[str]:
    """The full ffmpeg argument list for one clip."""
    command = ["ffmpeg", "-v", "error", "-nostdin", "-y"]
    if plan.codec == "h264_vaapi":
        # Device selection belongs before the input, like any other decoder flag.
        command += ["-vaapi_device", "/dev/dri/renderD128"]

    command += ["-ss", f"{plan.source_start_s:.3f}", "-i", str(plan.source)]
    command += ["-map", "0:v:0"]
    if plan.audio:
        # Optional: a silent source must not fail the whole clip.
        command += ["-map", "0:a:0?"]
    # -dn drops the input's data streams, which on the Action 4 are djmd, dbgi and a
    # timecode track. The mp4 muxer then writes a timecode track of its own from the
    # video stream's timecode, so the output still came back as video plus tmcd until
    # the muxer was told not to.
    command += ["-sn", "-dn", "-write_tmcd", "0"]

    if plan.mode == "fast":
        # Stream copy cannot filter, so nothing is normalized here and the cut lands
        # on the nearest keyframe. The caller records the mode so the report can say
        # the duration is approximate.
        command += ["-t", f"{plan.out_duration_s:.3f}", "-c", "copy"]
        if not plan.audio:
            command += ["-an"]
        command.append(str(plan.output))
        return command

    # A frame count rather than -t. The window rarely starts on a source frame
    # boundary, and -t then measures against the fps filter's own grid and can land a
    # frame short: 3.000 s from 2.500 s of a 25 fps source measured 2.96. Asking for
    # exactly 75 frames is the same intent stated in the unit the output is made of.
    command += ["-frames:v", str(plan.out_frames), "-vf", filter_chain(plan)]
    command += ["-c:v", plan.codec, *quality_flags(plan.codec, plan.crf)]
    if plan.pix_fmt is not None and plan.codec != "h264_vaapi":
        command += ["-pix_fmt", plan.pix_fmt]
    if plan.audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-an"]
    command.append(str(plan.output))
    return command


@dataclass(slots=True)
class ExportOverrides:
    """Command line values that win over configuration for one run."""

    no_audio: bool = False
    fps: float | None = None
    fast: bool = False
    rejects: bool = False


def even(value: int) -> int:
    """Encoders want even dimensions, and yuv420p needs them."""
    return max(2, value - (value % 2))


def fit_inside(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    """The largest even size that fits the box without ever enlarging the source."""
    if width <= 0 or height <= 0:
        return 0, 0
    factor = min(max_width / width, max_height / height, 1.0)
    return even(round(width * factor)), even(round(height * factor))


def is_fps_converted(source_fps: float, target_fps: float, tolerance: float = 0.01) -> bool:
    """Whether reaching the target means resampling rather than dropping whole frames.

    50 to 25 takes every other frame and 25 to 25 takes every frame; both are honest.
    30 to 25 has to invent a cadence, and that is what the report flags.
    """
    if source_fps <= 0 or target_fps <= 0:
        return False
    ratio = source_fps / target_fps
    return abs(ratio - round(ratio)) > tolerance


def dominant_fps(manifest: Manifest) -> float:
    """The most common frame rate among the selected clips, ties going to the lower.

    A tie broken by frame rate rather than by iteration order keeps the target stable
    across runs, which is the whole point of recording it.
    """
    rates = Counter(
        round(manifest.files[segment.file_id].fps, 3)
        for segment in manifest.segments.values()
        if segment.outcome == "selected" and segment.file_id in manifest.files
    )
    rates.pop(0.0, None)
    if not rates:
        return 25.0
    most = max(rates.values())
    return min(rate for rate, count in rates.items() if count == most)


def resolve_target_fps(
    manifest: Manifest, config: AutocutConfig, overrides: ExportOverrides | None = None
) -> float:
    """The frame rate every output of this run will have.

    An explicit request wins, then a numeric setting, then the target this project
    already exported at, and only then the footage. Reusing the recorded target is
    what keeps a second export from re-encoding everything because one clip was
    deselected and moved the mode.
    """
    overrides = overrides or ExportOverrides()
    if overrides.fps is not None:
        return overrides.fps
    if not isinstance(config.export.fps, str):
        return float(config.export.fps)
    if manifest.export.target_fps:
        return manifest.export.target_fps
    return dominant_fps(manifest)


def plan_export(
    segment: Segment,
    source: SourceFile,
    manifest: Manifest,
    config: AutocutConfig,
    overrides: ExportOverrides | None = None,
    output: Path | None = None,
) -> ExportPlan:
    """Decide everything about one clip's output, from the window to the geometry."""
    overrides = overrides or ExportOverrides()
    export = config.export
    target_fps = resolve_target_fps(manifest, config, overrides)
    source_class = source.source_class

    ratio = _slow_motion_ratio(source, target_fps, config)
    out_duration = segment.target_duration_s or config.selection.target_duration_seconds
    source_duration = out_duration / ratio
    start = _window_start(segment, source, source_duration)

    scale_w, scale_h = fit_inside(
        source.display_width, source.display_height, export.max_width, export.max_height
    )
    # A clip already inside the box needs no scale filter at all.
    if (scale_w, scale_h) == (source.display_width, source.display_height):
        scale_w, scale_h = 0, 0

    geometry = _vertical_geometry(source, scale_w, scale_h, export)

    return ExportPlan(
        source=source.path,
        output=output or Path(),
        source_start_s=start,
        source_duration_s=source_duration,
        out_duration_s=out_duration,
        target_fps=target_fps,
        mode="fast" if overrides.fast else export.mode,
        codec=export.codec,
        crf=export.crf,
        pix_fmt=None if export.pix_fmt == "passthrough" else export.pix_fmt,
        keep_audio=not (overrides.no_audio or export.remove_audio.get(source_class)),
        scale_w=geometry.scale_w or None,
        scale_h=geometry.scale_h or None,
        slow_motion_ratio=ratio,
        vertical_strategy=export.vertical_strategy,
        is_vertical=source.is_vertical,
        pad_w=geometry.pad_w or None,
        pad_h=geometry.pad_h or None,
        blur_radius=geometry.blur_radius,
        crop_w=geometry.crop_w or None,
        crop_h=geometry.crop_h or None,
        lut=_lut(export.lut.get(source_class)),
        lens_correction=export.lens_correction.get(source_class),
        fps_converted=is_fps_converted(source.fps, target_fps),
    )


def _lut(path: Path | None) -> Path | None:
    """A LUT path, or None when configuration left it unset.

    TOML has no null, so a class with no LUT is written as an empty string and
    arrives here as ``Path(".")``. That is truthy and would put ``lut3d=file=.`` in
    the filter chain, which fails the whole clip.
    """
    if path is None or str(path) in ("", "."):
        return None
    return path


def _slow_motion_ratio(source: SourceFile, target_fps: float, config: AutocutConfig) -> int:
    """The integer slowdown for this clip, or 1 for real time.

    Only whole ratios are used. Half speed from 50 to 25 shows every frame the camera
    took; anything else would have to interpolate, which is slow and shows.
    """
    if not config.export.slow_motion_auto.get(source.source_class):
        return 1
    if target_fps <= 0 or source.fps < 2 * target_fps:
        return 1
    return max(1, int(round(source.fps / target_fps)))


def _window_start(segment: Segment, source: SourceFile, source_duration: float) -> float:
    """Where to start reading, keeping the window inside the file around the center."""
    center = segment.best_center_s
    if center is None:
        start, stop = segment.start_s, segment.end_s
        center = (start + stop) / 2.0
    start = center - source_duration / 2.0
    limit = source.duration_s - source_duration
    if limit <= 0:
        return 0.0
    return max(0.0, min(start, limit))


@dataclass(frozen=True, slots=True)
class _Geometry:
    """Sizes for the scale, crop and pad filters, zero meaning "no such filter"."""

    scale_w: int = 0
    scale_h: int = 0
    crop_w: int = 0
    crop_h: int = 0
    pad_w: int = 0
    pad_h: int = 0
    blur_radius: int = 0


def _vertical_geometry(
    source: SourceFile, scale_w: int, scale_h: int, export: ExportConfig
) -> _Geometry:
    """What a vertical clip has to become under the configured strategy.

    The canvas aspect is the aspect of the configured maximum, which is what the
    target format means in practice: a 3840x2160 maximum is a 16:9 project.
    """
    plain = _Geometry(scale_w=scale_w, scale_h=scale_h)
    if not source.is_vertical or export.vertical_strategy == "exclude":
        return plain

    # The filters run after the scale, so they work on the scaled size when there is
    # one and on the source size when the clip already fits.
    width = scale_w or source.display_width
    height = scale_h or source.display_height
    if width <= 0 or height <= 0:
        return plain
    aspect = export.max_width / export.max_height

    if export.vertical_strategy == "center_crop":
        crop_h = even(round(width / aspect))
        return _Geometry(scale_w=scale_w, scale_h=scale_h, crop_w=width, crop_h=min(crop_h, height))

    pad_h, pad_w = height, even(round(height * aspect))
    if pad_w > export.max_width:
        pad_w = even(export.max_width)
        pad_h = even(round(pad_w / aspect))
        width, height = fit_inside(width, height, pad_w, pad_h)
        scale_w, scale_h = width, height
    return _Geometry(
        scale_w=scale_w,
        scale_h=scale_h,
        pad_w=pad_w,
        pad_h=pad_h,
        # Proportional to the canvas so the backdrop looks the same at any resolution,
        # and bounded by boxblur's own limit of half the shorter side.
        blur_radius=max(2, min(pad_w // 40, min(pad_w, pad_h) // 2 - 1)),
    )

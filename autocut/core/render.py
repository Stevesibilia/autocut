"""The finished edit as one file: the exported clips joined, with the track over them.

SPEC.md section 2 keeps editing out of AutoCut, and this is the exception the user
asked for. A holiday edit whose clips, order and lengths are all decided before an
editor opens needs nothing from CapCut except the export, so joining that export is the
whole job: hard cuts, one track, no transitions and no titles.

It costs seconds because nothing is re-encoded. The export planner gives every clip the
same codec, pixel format, resolution and frame rate by construction, so the clips
concatenate by stream copy and only the track is encoded. Clips that do not match are
refused rather than joined: the concat demuxer will happily produce a file that plays
for ten seconds and then falls apart, and a broken render is worse than no render.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from autocut.core.avmux import (
    CONCAT_TIMEOUT_S,
    concat_command,
    probe_duration,
    run_ffmpeg,
    write_concat_list,
)
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.export import ExportResult, export_clips, export_is_current
from autocut.core.ffmpeg_cmd import ExportOverrides
from autocut.core.manifest import Manifest, Segment

#: The keys that have to agree across the clips for a stream copy concat to be valid.
VIDEO_KEYS = ("codec_name", "width", "height", "pix_fmt", "r_frame_rate")
AUDIO_KEYS = ("codec_name", "sample_rate", "channels")


@dataclass(slots=True)
class StreamInfo:
    """What one exported clip is, in the terms the concat demuxer cares about."""

    path: Path
    video: dict[str, object] = field(default_factory=dict)
    audio: dict[str, object] | None = None
    duration_s: float = 0.0


@dataclass(slots=True)
class PartsCheck:
    """Whether the exported clips can be joined without re-encoding."""

    clips: list[StreamInfo] = field(default_factory=list)
    error: str | None = None

    @property
    def uniform(self) -> bool:
        return self.error is None and bool(self.clips)

    @property
    def has_audio(self) -> bool:
        return bool(self.clips) and self.clips[0].audio is not None

    @property
    def total_s(self) -> float:
        return sum(clip.duration_s for clip in self.clips)


@dataclass(slots=True)
class RenderResult:
    """What one render did."""

    path: Path | None = None
    fingerprint: str = ""
    duration_s: float = 0.0
    size_bytes: int = 0
    clips: int = 0
    has_audio: bool = False
    track: Path | None = None
    fade_out_s: float = 0.0
    frame: tuple[int, int] = (0, 0)
    """The common frame the clips were exported at, which is the render's own size."""

    reused: bool = False
    export: ExportResult | None = None
    skipped_reason: str | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.path is not None and not self.errors


def selected_in_order(manifest: Manifest) -> list[Segment]:
    """The edit, in the order it will play."""
    return sorted(
        (segment for segment in manifest.segments.values() if segment.outcome == "selected"),
        key=lambda segment: (segment.order if segment.order is not None else 0, segment.id),
    )


def render_path(manifest: Manifest, config: AutocutConfig, out: Path | None = None) -> Path:
    """Where the render goes: beside ``_selects/``, not inside it.

    Inside would put a file CapCut imports as a clip into the folder the user drags in.
    """
    if out is not None:
        # Resolved: a relative name that begins with a dash would reach ffmpeg as an
        # option rather than as the file to write.
        return Path(out).expanduser().resolve()
    return (Path(manifest.output_dir) / config.render.filename).expanduser().resolve()


def resolve_track(manifest: Manifest, track: Path | None = None) -> Path | None:
    """Which track this render should carry.

    ``--track`` wins, then the track the edit was synced against, then whatever track
    is loaded. The synced one is preferred rather than merely accepted: a project that
    has been synced was cut to that file, and muxing another one over cuts made for it
    would be a silent mismatch.
    """
    for candidate in (track, manifest.soundtrack.synced_audio_path, manifest.soundtrack.audio_path):
        if candidate is not None and Path(candidate).exists():
            return Path(candidate)
    return None


def _file_identity(path: Path | None) -> list[object]:
    """A path with its size and modification time, or nothing.

    Size and mtime rather than a hash, for the reason ``montage`` gives: hashing a
    hundred megabytes of track to decide whether to spend ten seconds joining files is
    not a saving.
    """
    if path is None:
        return []
    try:
        stat = Path(path).stat()
    except OSError:
        return [str(path), None, None]
    return [str(path), stat.st_size, int(stat.st_mtime)]


def render_fingerprint(
    manifest: Manifest,
    config: AutocutConfig,
    track: Path | None,
    fade_out_s: float | None = None,
) -> str:
    """What this render was made from: the export, the track and the fade.

    Built on each clip's own export fingerprint rather than on the selection: that
    digest already covers the window, the frame rate, the codec and every per class
    option, so a change that would re-encode a clip also re-renders the file, and a
    change that would not, does not.
    """
    fade = config.render.fade_out_seconds if fade_out_s is None else fade_out_s
    payload: list[object] = [
        config.render.filename,
        round(float(fade), 3),
        config.render.audio_bitrate,
        _file_identity(track),
    ]
    for segment in selected_in_order(manifest):
        payload.append([segment.id, segment.order, segment.export_fingerprint])
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()[:16]


def is_current(
    manifest: Manifest,
    config: AutocutConfig,
    track: Path | None,
    out: Path | None = None,
) -> bool:
    """Whether the file on disk is the render this project would produce now."""
    state = manifest.render
    if state.fingerprint is None or state.path is None:
        return False
    output = render_path(manifest, config, out)
    if Path(state.path) != output or not output.exists():
        return False
    return state.fingerprint == render_fingerprint(manifest, config, track)


def probe_streams(path: Path) -> StreamInfo:
    """One ffprobe per clip, kept to what decides whether the clips concatenate."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    info = StreamInfo(path=Path(path))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        payload = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return info
    for stream in payload.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and not info.video:
            info.video = {key: stream.get(key) for key in VIDEO_KEYS}
        elif kind == "audio" and info.audio is None:
            info.audio = {key: stream.get(key) for key in AUDIO_KEYS}
    try:
        info.duration_s = float(payload.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        info.duration_s = 0.0
    return info


def check_parts_uniform(paths: list[Path]) -> PartsCheck:
    """Whether these files can be joined by stream copy, and what they are.

    A fast mode export stream copies from the sources, so a folder can hold a 4K 30 fps
    clip next to a 2.7K 60 fps one and every one of them is a valid file. Joined, they
    are not: the demuxer writes a container whose later clips do not match its header.
    """
    check = PartsCheck()
    for path in paths:
        if not Path(path).exists():
            check.error = f"{Path(path).name} is missing from the export"
            return check
        check.clips.append(probe_streams(Path(path)))

    if not check.clips:
        check.error = "there are no exported clips to join"
        return check

    first = check.clips[0]
    if not first.video:
        check.error = f"{first.path.name} has no video stream"
        return check
    for clip in check.clips[1:]:
        if clip.video != first.video:
            check.error = (
                f"{clip.path.name} is {_describe(clip.video)} and {first.path.name} is "
                f"{_describe(first.video)}, so they cannot be joined without "
                "re-encoding. The export puts every clip on one common frame for a "
                "render, so this should not happen: the folder probably holds clips "
                "from an older export. Delete _selects/ and render again, and if it "
                "happens on a fresh export it is a bug worth reporting."
            )
            return check
        if (clip.audio is None) != (first.audio is None):
            check.error = (
                f"{clip.path.name} and {first.path.name} disagree about audio: one has a "
                "track and the other has none, which cannot be joined by stream copy. "
                "Set audio removal the same way for every source class and re-export."
            )
            return check
        if clip.audio is not None and first.audio is not None and clip.audio != first.audio:
            check.error = (
                f"{clip.path.name} and {first.path.name} have different audio formats, "
                "which cannot be joined by stream copy. Re-export with one set of "
                "settings, or remove the clip audio and use a track."
            )
            return check
    return check


def _describe(video: dict[str, object]) -> str:
    """One clip's video parameters, in the words the message needs."""
    return (
        f"{video.get('codec_name')} {video.get('width')}x{video.get('height')} "
        f"{video.get('pix_fmt')} at {video.get('r_frame_rate')}"
    )


def exported_clips(manifest: Manifest) -> tuple[list[Path], list[tuple[str, str]]]:
    """The exported file of every selected clip, in edit order."""
    paths: list[Path] = []
    errors: list[tuple[str, str]] = []
    for segment in selected_in_order(manifest):
        if segment.exported_path is None:
            errors.append((segment.id, "this clip has no exported file"))
            continue
        paths.append(Path(segment.exported_path))
    return paths, errors


def render_edit(
    manifest: Manifest,
    config: AutocutConfig,
    track: Path | None = None,
    progress: ProgressCallback = null_progress,
    out: Path | None = None,
    force: bool = False,
    overrides: ExportOverrides | None = None,
) -> RenderResult:
    """Write the finished file, exporting first when the clips are not current.

    The export is the render's input, so a render over a stale export would join the
    previous edit. Rather than refuse, it exports: the user asked for the finished file
    and the clips are the means, not the request.
    """
    fade = float(config.render.fade_out_seconds)
    chosen = resolve_track(manifest, track)
    output = render_path(manifest, config, out)
    result = RenderResult(track=chosen, fade_out_s=fade)

    if not selected_in_order(manifest):
        result.skipped_reason = "nothing is selected"
        return result

    # The clips are the render's input, and they have to be joinable. A stream copied
    # clip carries whatever its source was, which no planner can make uniform, so this
    # is refused before anything is encoded rather than after twenty-nine clips.
    overrides = replace(overrides or ExportOverrides(), uniform_frame=True)
    if overrides.fast or config.export.mode == "fast":
        result.errors.append(
            (
                "render",
                "a render needs precise mode: fast mode copies each source as it is, so "
                'the clips cannot be given one frame. Set export.mode = "precise" and '
                "export again.",
            )
        )
        return result

    export_current = export_is_current(manifest, config, overrides)
    if not force and export_current and is_current(manifest, config, chosen, out):
        state = manifest.render
        result.path = Path(state.path) if state.path else None
        result.fingerprint = state.fingerprint or ""
        result.duration_s = state.duration_s
        result.size_bytes = state.size_bytes
        result.clips = state.clips
        result.has_audio = state.has_audio
        result.reused = True
        progress(ProgressEvent(stage="render", current=1, total=1, path=result.path))
        return result

    if not export_current:
        progress(
            ProgressEvent(stage="render", current=0, total=3, message="exporting the clips first")
        )
        result.export = export_clips(manifest, config, progress, overrides)
        if result.export.failed:
            result.errors.append(("export", f"{result.export.failed} clips failed to export"))
            return result

    paths, missing = exported_clips(manifest)
    result.errors.extend(missing)
    if missing:
        return result

    progress(ProgressEvent(stage="render", current=1, total=3, message="checking the clips"))
    check = check_parts_uniform(paths)
    if not check.uniform:
        result.errors.append(("render", check.error or "the clips cannot be joined"))
        return result

    progress(ProgressEvent(stage="render", current=2, total=3, path=output, message="joining"))
    error = _join(paths, chosen, output, check, config, fade)
    if error is not None:
        result.errors.append(("render", error))
        return result

    result.path = output
    result.duration_s = probe_duration(output)
    result.size_bytes = output.stat().st_size
    result.clips = len(paths)
    result.has_audio = chosen is not None or check.has_audio
    result.fingerprint = render_fingerprint(manifest, config, chosen, fade)
    result.frame = (manifest.export.frame_width or 0, manifest.export.frame_height or 0)
    record(manifest, result)
    progress(ProgressEvent(stage="render", current=3, total=3, path=output))
    return result


def _join(
    paths: list[Path],
    track: Path | None,
    output: Path,
    check: PartsCheck,
    config: AutocutConfig,
    fade_out_s: float,
) -> str | None:
    """Concatenate into a temporary file and only then take the final name.

    A render is watched from the file manager, and a player may well have the previous
    one open. Writing beside it and renaming means the old file is replaced whole or not
    at all, and never half overwritten under something that is reading it.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    list_file = output.parent / f".{output.stem}-parts.txt"
    write_concat_list(paths, list_file)
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix}")
    error = run_ffmpeg(
        concat_command(
            list_file,
            track,
            temporary,
            # The output is bounded only when a track is muxed, because that is the
            # only stream that outlives the video: the padded audio has to be cut back
            # to the edit, while the clips' own audio ends where they do.
            duration_s=check.total_s if track is not None else 0.0,
            fade_out_s=fade_out_s,
            audio_bitrate=config.render.audio_bitrate,
            keep_clip_audio=check.has_audio,
        ),
        CONCAT_TIMEOUT_S,
        temporary,
    )
    list_file.unlink(missing_ok=True)
    if error is not None:
        temporary.unlink(missing_ok=True)
        return error
    temporary.replace(output)
    return None


def record(manifest: Manifest, result: RenderResult) -> None:
    """Put the render on the manifest, so an unchanged edit renders nothing next time."""
    manifest.render.fingerprint = result.fingerprint
    manifest.render.path = result.path
    manifest.render.duration_s = result.duration_s
    manifest.render.size_bytes = result.size_bytes
    manifest.render.clips = result.clips
    manifest.render.has_audio = result.has_audio
    manifest.render.fade_out_s = result.fade_out_s
    manifest.render.track_path = result.track
    manifest.render.rendered_at = datetime.now(UTC)

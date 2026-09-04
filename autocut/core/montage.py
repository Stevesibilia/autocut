"""The selected edit as one small file, so it can be watched before it is exported.

The Review screen previews one clip at a time, and switching a player between
twenty-nine sources leaves a gap at every cut, which is the one thing a person is
trying to judge. So the clips are rendered small and joined: what comes out plays the
way CapCut will play it, with the track over it, in a file that takes seconds to make.

One ffmpeg pass per clip and then a concat, rather than one filter graph over every
input. Twenty-nine 4K decoders at once is gigabytes of memory and no progress to
report, and a re-encode of the joined parts would cost time for nothing, since the
parts are encoded to identical parameters and therefore concatenate by stream copy.

Windows come from ``plan_export``, so the montage cuts what the export will cut: hand
set bounds, then beat bounds, then the searched window, in that order. A preview that
disagreed with the export would be worse than no preview.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.ffmpeg_cmd import ExportPlan, even, plan_export, resolve_target_fps
from autocut.core.manifest import Manifest, Segment, SourceFile

PREVIEW_DIRNAME = "preview"
PARTS_DIRNAME = "parts"
MONTAGE_FILENAME = "montage.mp4"
INDEX_FILENAME = "montage.json"

#: A part is seconds of work at 360 px; a whole montage of a long holiday is minutes.
PART_TIMEOUT_S = 300.0
CONCAT_TIMEOUT_S = 600.0


class MontageCancelled(Exception):  # noqa: N818 - a cancellation, not an error
    """Raised by the progress callback to stop between clips."""


@dataclass(slots=True)
class Part:
    """One clip of the montage, as a file and as a span of the whole."""

    order: int
    segment_id: str
    path: Path
    duration_s: float
    start_s: float = 0.0
    reused: bool = False

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass(slots=True)
class MontageResult:
    """What one render did."""

    path: Path | None = None
    index_path: Path | None = None
    fingerprint: str = ""
    parts: list[Part] = field(default_factory=list)
    rendered: int = 0
    reused: int = 0
    duration_s: float = 0.0
    has_audio: bool = False
    reused_montage: bool = False
    skipped_reason: str | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.path is not None and not self.errors


def preview_dir(manifest: Manifest) -> Path:
    return Path(manifest.output_dir) / PREVIEW_DIRNAME


def parts_dir(manifest: Manifest) -> Path:
    return preview_dir(manifest) / PARTS_DIRNAME


def selected_in_order(manifest: Manifest) -> list[Segment]:
    """The edit, in the order it will play."""
    return sorted(
        (segment for segment in manifest.segments.values() if segment.outcome == "selected"),
        key=lambda segment: (segment.order if segment.order is not None else 0, segment.id),
    )


def _file_identity(path: Path | None) -> list[object]:
    """A path with its size and modification time, or nothing.

    Size and mtime rather than a hash: hashing a hundred megabytes of track, or
    gigabytes of footage, to decide whether to spend twenty seconds rendering is not a
    saving. A file replaced under the same name has a different mtime.
    """
    if path is None:
        return []
    try:
        stat = path.stat()
    except OSError:
        return [str(path), None, None]
    return [str(path), stat.st_size, int(stat.st_mtime)]


def part_fingerprint(
    segment: Segment, source: SourceFile, plan: ExportPlan, height: int, config: AutocutConfig
) -> str:
    """What this one part was made from.

    Per part rather than only per montage, so rejecting one clip re-renders the concat
    and nothing else: the other twenty-eight parts are already on disk and provably
    unchanged.
    """
    payload = [
        segment.id,
        round(plan.source_start_s, 4),
        round(plan.source_duration_s, 4),
        round(plan.out_duration_s, 4),
        round(plan.target_fps, 3),
        plan.slow_motion_ratio,
        height,
        config.gui.montage_preset,
        config.gui.montage_crf,
        _file_identity(_read_from(source)),
    ]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()[:16]


def montage_fingerprint(manifest: Manifest, config: AutocutConfig, track: Path | None) -> str:
    """What the whole montage was made from: the edit, the geometry and the track."""
    selected = selected_in_order(manifest)
    target_fps = resolve_target_fps(manifest, config)
    payload: list[object] = [
        round(target_fps, 3),
        config.gui.montage_height,
        config.gui.montage_preset,
        config.gui.montage_crf,
        _file_identity(track),
    ]
    for segment in selected:
        source = manifest.files.get(segment.file_id)
        if source is None:
            continue
        plan = plan_export(segment, source, manifest, config)
        payload.append(
            [
                segment.id,
                segment.order,
                round(plan.source_start_s, 4),
                round(plan.out_duration_s, 4),
                _file_identity(_read_from(source)),
            ]
        )
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()[:16]


def is_current(manifest: Manifest, config: AutocutConfig, track: Path | None) -> bool:
    """Whether the montage on disk is the montage this edit would produce."""
    preview = manifest.preview
    if preview.fingerprint is None or preview.path is None:
        return False
    if not Path(preview.path).exists():
        return False
    return preview.fingerprint == montage_fingerprint(manifest, config, track)


def _read_from(source: SourceFile) -> Path:
    """The proxy when there is one. A 360 px montage has nothing to gain from the 4K."""
    return Path(source.proxy_path or source.path)


def part_command(plan: ExportPlan, height: int, config: AutocutConfig, output: Path) -> list[str]:
    """One clip at montage size, no audio, encoded for speed.

    Not ``build_export_command``: this output has different rules. No LUT, no lens
    correction and no vertical strategy, because the montage answers "does the
    sequence work" and not "what will the export look like"; no audio, because the
    clips are silent in the export too and the track is muxed once at the end; and a
    fixed frame rate, so every part concatenates with every other by construction.
    """
    scale = f"scale=-2:{height}:flags=fast_bilinear"
    filters = [scale, f"fps={plan.target_fps:g}"]
    if plan.slow_motion_ratio > 1:
        # The same slow motion the export applies, or the montage would run through a
        # 100 fps clip four times faster than the edit will.
        filters.insert(0, f"setpts={plan.slow_motion_ratio}*PTS")
    return [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        f"{plan.source_start_s:.3f}",
        "-i",
        str(plan.source),
        "-map",
        "0:v:0",
        "-sn",
        "-dn",
        "-an",
        "-frames:v",
        str(plan.out_frames),
        "-vf",
        ",".join(filters),
        "-c:v",
        "libx264",
        "-preset",
        config.gui.montage_preset,
        "-crf",
        str(config.gui.montage_crf),
        # A keyframe per second keeps the concat's seeks cheap.
        "-g",
        str(max(1, round(plan.target_fps))),
        "-pix_fmt",
        "yuv420p",
        str(output),
    ]


def concat_command(
    list_file: Path, track: Path | None, output: Path, duration_s: float = 0.0
) -> list[str]:
    """Join the parts by stream copy, muxing the track when there is one.

    The video length is the montage's length, never the track's. ``-shortest`` was the
    obvious flag and it is the wrong one: measured on the real project, a twenty
    second track cut a seventy-seven second edit down to twenty seconds, which is the
    opposite of a preview of the edit. So the audio is padded with silence and the
    output is cut to the video's own duration: a short track leaves the rest of the
    montage silent, and a long one is trimmed.
    """
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
    ]
    if track is not None:
        command += ["-i", str(track)]
    command += ["-map", "0:v:0"]
    if track is not None:
        # Re-encoded rather than copied: the track can be anything Suno felt like
        # returning, and an mp4 will not hold every one of them.
        command += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "160k", "-af", "apad"]
    else:
        command += ["-an"]
    # -dn drops the parts' data streams, and -write_tmcd 0 stops the mp4 muxer writing
    # a timecode track of its own from the copied video stream: without it the montage
    # comes out as video, audio and an unknown data stream, which is a file some
    # players refuse. The export command carries the same pair for the same reason.
    command += ["-sn", "-dn", "-write_tmcd", "0", "-c:v", "copy", "-movflags", "+faststart"]
    if duration_s > 0:
        command += ["-t", f"{duration_s:.3f}"]
    command.append(str(output))
    return command


def probe_duration(path: Path) -> float:
    """The duration ffmpeg says the file has, which is what the index has to use.

    Measured rather than computed from the frame count: the index is what a player
    maps a position onto, so it has to describe the file that exists and not the file
    that was asked for.
    """
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        return float(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


def write_index(manifest: Manifest, parts: list[Part], output: Path) -> Path:
    """``montage.json``: which clip is playing at any second of the montage."""
    payload = {
        "montage": str(output.name),
        "clips": [
            {
                "order": part.order,
                "segment_id": part.segment_id,
                "start_s": round(part.start_s, 4),
                "end_s": round(part.end_s, 4),
                "duration_s": round(part.duration_s, 4),
            }
            for part in parts
        ],
        "duration_s": round(parts[-1].end_s, 4) if parts else 0.0,
    }
    path = output.parent / INDEX_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    del manifest  # the index describes the montage, not the project
    return path


def read_index(path: Path) -> list[Part]:
    """The index back as parts, for a player that did not render the montage itself."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    parts: list[Part] = []
    for entry in payload.get("clips", []):
        try:
            parts.append(
                Part(
                    order=int(entry["order"]),
                    segment_id=str(entry["segment_id"]),
                    path=Path(),
                    duration_s=float(entry["duration_s"]),
                    start_s=float(entry["start_s"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return parts


def clip_at(parts: list[Part], seconds: float) -> Part | None:
    """Which clip is on screen at this position. ``None`` before the first or after the last."""
    for part in parts:
        if part.start_s <= seconds < part.end_s:
            return part
    if parts and seconds >= parts[-1].end_s:
        return parts[-1]
    return None


def render_parts(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
) -> tuple[list[Part], list[tuple[str, str]]]:
    """One file per selected clip, reusing the ones already on disk.

    Raises ``MontageCancelled`` when the progress callback does, which is how the
    worker stops it between clips.
    """
    selected = selected_in_order(manifest)
    height = even(config.gui.montage_height)
    directory = parts_dir(manifest)
    directory.mkdir(parents=True, exist_ok=True)
    parts: list[Part] = []
    errors: list[tuple[str, str]] = []
    total = len(selected)

    for index, segment in enumerate(selected, start=1):
        source = manifest.files.get(segment.file_id)
        if source is None:
            errors.append((segment.id, "the manifest has no file for this segment"))
            continue
        # The plan is frozen, so the proxy substitution is a copy rather than a poke.
        plan = replace(plan_export(segment, source, manifest, config), source=_read_from(source))
        digest = part_fingerprint(segment, source, plan, height, config)
        # Named by what it is, not by where it sits: the position in the edit is the
        # concat list's business, and putting it in the name meant that dropping one
        # clip renamed every part after it and re-rendered them all, which is the one
        # thing the per part fingerprint exists to prevent.
        path = directory / f"{digest}.mp4"
        reused = path.exists() and path.stat().st_size > 0
        if not reused:
            error = _run(part_command(plan, height, config, path), PART_TIMEOUT_S, path)
            if error is not None:
                errors.append((segment.id, error))
                progress(
                    ProgressEvent(
                        stage="export", current=index, total=total, path=path, message=error
                    )
                )
                continue
        duration = probe_duration(path)
        parts.append(
            Part(
                order=segment.order or index,
                segment_id=segment.id,
                path=path,
                duration_s=duration,
                reused=reused,
            )
        )
        progress(
            ProgressEvent(
                stage="export",
                current=index,
                total=total,
                path=path,
                extra={"reused": reused, "montage_part": True},
            )
        )

    start = 0.0
    for part in parts:
        part.start_s = start
        start += part.duration_s
    return parts, errors


def concat_montage(parts: list[Part], track: Path | None, output: Path) -> str | None:
    """Join the parts into ``output``. Returns an error message, or ``None``."""
    if not parts:
        return "there are no parts to join"
    duration = parts[-1].end_s
    output.parent.mkdir(parents=True, exist_ok=True)
    list_file = output.parent / "parts.txt"
    # Single quotes doubled, which is how the concat demuxer escapes them.
    lines = [f"file '{str(part.path).replace(chr(39), chr(39) * 2)}'" for part in parts]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _run(concat_command(list_file, track, output, duration), CONCAT_TIMEOUT_S, output)


def _run(command: list[str], timeout: float, output: Path) -> str | None:
    """Run ffmpeg. Returns an error message, or ``None`` when the file was written."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return "ffmpeg not found on PATH"
    except subprocess.SubprocessError as exc:
        return str(exc)
    if completed.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        for line in completed.stderr.splitlines():
            if line.strip():
                return line.strip()
        return f"ffmpeg exit status {completed.returncode}"
    return None


def build_montage(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
    track: Path | None = None,
    force: bool = False,
) -> MontageResult:
    """Render the montage for the current edit, or hand back the one already built.

    The fingerprint is checked first: pressing Play all twice on an edit nobody has
    touched has to cost nothing, which is the difference between a preview people use
    and one they avoid.
    """
    selected = selected_in_order(manifest)
    if not selected:
        return MontageResult(skipped_reason="nothing is selected")

    fingerprint = montage_fingerprint(manifest, config, track)
    output = preview_dir(manifest) / MONTAGE_FILENAME
    if not force and is_current(manifest, config, track):
        existing = Path(manifest.preview.path or output)
        return MontageResult(
            path=existing,
            index_path=Path(manifest.preview.index_path) if manifest.preview.index_path else None,
            fingerprint=fingerprint,
            parts=read_index(Path(manifest.preview.index_path))
            if manifest.preview.index_path
            else [],
            duration_s=manifest.preview.duration_s,
            has_audio=manifest.preview.has_audio,
            reused_montage=True,
        )

    parts, errors = render_parts(manifest, config, progress)
    result = MontageResult(fingerprint=fingerprint, parts=parts, errors=errors)
    result.rendered = sum(1 for part in parts if not part.reused)
    result.reused = sum(1 for part in parts if part.reused)
    if not parts:
        result.skipped_reason = "no clip could be rendered"
        return result

    error = concat_montage(parts, track, output)
    if error is not None:
        result.errors.append(("montage", error))
        return result

    result.path = output
    result.duration_s = probe_duration(output)
    result.has_audio = track is not None
    result.index_path = write_index(manifest, parts, output)
    _forget_unused_parts(manifest, parts)
    record(manifest, result)
    return result


def record(manifest: Manifest, result: MontageResult) -> None:
    """Put the montage on the manifest, so the next Play all can skip the render."""
    manifest.preview.fingerprint = result.fingerprint
    manifest.preview.path = result.path
    manifest.preview.index_path = result.index_path
    manifest.preview.duration_s = result.duration_s
    manifest.preview.clips = len(result.parts)
    manifest.preview.has_audio = result.has_audio
    manifest.preview.built_at = datetime.now(UTC)


def _forget_unused_parts(manifest: Manifest, parts: list[Part]) -> None:
    """Delete the parts this montage does not use.

    A part is keyed by what it was made from, so a changed clip leaves its old part
    behind. Sweeping here keeps ``preview/parts/`` from growing by one file per edit
    for the length of a review session.
    """
    keep = {part.path.name for part in parts}
    directory = parts_dir(manifest)
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink(missing_ok=True)


def clear_preview(manifest: Manifest) -> int:
    """Remove the montage, its parts and its index. Returns how many files went.

    Called by the export's stale sweep: a preview built from an edit that no longer
    exists is exactly as stale as a clip file from a dropped selection.
    """
    directory = preview_dir(manifest)
    if not directory.is_dir():
        return 0
    removed = sum(1 for path in directory.rglob("*") if path.is_file())
    shutil.rmtree(directory, ignore_errors=True)
    manifest.preview = type(manifest.preview)()
    return removed

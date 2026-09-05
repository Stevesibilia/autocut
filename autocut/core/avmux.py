"""Joining finished clips and muxing a track onto them, without touching the video.

Two outputs need exactly this: the 360 px montage preview and the final render. Both
concatenate files that were encoded to identical parameters, so both join by stream
copy, and both put one track over the result. The difference is quality and a fade,
which are arguments rather than a second implementation.

Everything here is about the container rather than the picture. Nothing in this module
decides what a clip looks like; that is ``ffmpeg_cmd`` for the export and ``montage``
for the preview.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: A concat of clips already on disk is I/O and a container rewrite, but a long holiday
#: edit is still gigabytes of it.
CONCAT_TIMEOUT_S = 600.0

#: The concat demuxer escapes a single quote by doubling it.
_QUOTE = chr(39)


def write_concat_list(paths: list[Path], list_file: Path) -> Path:
    """Write the demuxer's file list, quoting names that contain anything awkward."""
    list_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"file '{str(path).replace(_QUOTE, _QUOTE * 2)}'" for path in paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_file


def audio_filter(duration_s: float, fade_out_s: float) -> str:
    """Pad the track with silence, then fade it out at the end of the edit.

    ``apad`` rather than ``-shortest``: measured on the real project, a twenty second
    track cut a seventy-seven second edit down to twenty seconds, which is the opposite
    of what either output is for. A short track leaves the rest silent and a long one is
    trimmed by the output duration, so the video's length always wins.

    The fade is placed against the edit's end rather than the track's, because that is
    where the file stops; a fade computed from the track would be cut off mid-way.
    """
    filters = ["apad"]
    if fade_out_s > 0 and duration_s > 0:
        start = max(0.0, duration_s - fade_out_s)
        filters.append(f"afade=t=out:st={start:.3f}:d={min(fade_out_s, duration_s):.3f}")
    return ",".join(filters)


def concat_command(
    list_file: Path,
    track: Path | None,
    output: Path,
    duration_s: float = 0.0,
    fade_out_s: float = 0.0,
    audio_bitrate: str = "160k",
    keep_clip_audio: bool = False,
) -> list[str]:
    """Join the listed files by stream copy, muxing the track when there is one.

    The video length is the edit's length, never the track's, which is what
    ``duration_s`` is for. ``keep_clip_audio`` copies the audio the clips already carry,
    and is ignored when a track is given: mixing the two is a decision nobody has asked
    for, and a track over ambience nobody chose is worse than either alone.
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
        # Re-encoded rather than copied: the track can be anything a generator felt
        # like returning, and an mp4 will not hold every one of them.
        command += [
            "-map",
            "1:a:0",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-af",
            audio_filter(duration_s, fade_out_s),
        ]
    elif keep_clip_audio:
        command += ["-map", "0:a:0", "-c:a", "copy"]
    else:
        command += ["-an"]
    # -dn drops the parts' data streams, and -write_tmcd 0 stops the mp4 muxer writing a
    # timecode track of its own from the copied video stream: without it the output
    # comes out as video, audio and an unknown data stream, which is a file some players
    # refuse. The export command carries the same pair for the same reason.
    command += ["-sn", "-dn", "-write_tmcd", "0", "-c:v", "copy", "-movflags", "+faststart"]
    if duration_s > 0:
        command += ["-t", f"{duration_s:.3f}"]
    command.append(str(output))
    return command


def probe_duration(path: Path) -> float:
    """The duration ffmpeg says the file has, which is what an index has to use.

    Measured rather than computed from the frame count: a player maps a position onto
    the file that exists, not onto the file that was asked for.
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


def run_ffmpeg(command: list[str], timeout: float, output: Path) -> str | None:
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

#!/usr/bin/env python3
"""Generate synthetic, public safe video fixtures into tests/fixtures/synthetic/.

Each fixture exercises one edge case named in SPEC.md section 14. Requires ffmpeg on
PATH. See ADR 8.

Several test runs can start at once (``make test`` in a shell while a container runs
``make docker-test``), so the script never writes into the fixture directory directly.
It returns immediately when every fixture is already there, and otherwise builds the
whole set in a private temporary directory and moves the files into place one atomic
rename at a time. Concurrent runs then duplicate work at worst; they never leave a
half written file for a reader to open. Pass ``--force`` to rebuild a complete set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic"
SIZE = "640x360"
FPS = 25
DUR = 6

# Every file main() leaves in OUT. Used to decide whether there is anything to do, so
# a new fixture has to be named here as well as built below or it is never generated.
EXPECTED: tuple[str, ...] = (
    "sharp_pan.mp4",
    "blurred.mp4",
    "overexposed.mp4",
    "underexposed.mp4",
    "static.mp4",
    "shaky.mp4",
    "multishot.mp4",
    "vertical_rot90.mp4",
    "with_audio.mp4",
    "small_320.mp4",
    "fifty_fps.mp4",
    "hevc_10bit.mp4",
    "click_120bpm.wav",
    "drone_embedded_srt.mp4",
)


def complete(directory: Path) -> bool:
    """Whether every expected fixture is present and not empty."""
    return all(
        (directory / name).is_file() and (directory / name).stat().st_size > 0 for name in EXPECTED
    )


def ff(*args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True)


def src(pattern: str = "testsrc2", dur: int = DUR, fps: int = FPS, size: str = SIZE) -> list[str]:
    return ["-f", "lavfi", "-i", f"{pattern}=size={size}:rate={fps}:duration={dur}"]


def dji_srt(path: Path, dur: int, heights: list[float]) -> None:
    """Write a DJI Mini 2 style telemetry track, one cue per second."""
    lines: list[str] = []
    for i in range(dur):
        h = heights[min(i, len(heights) - 1)]
        start = f"00:00:{i:02d},000"
        end = f"00:00:{i + 1:02d},000"
        lines += [
            str(i + 1),
            f"{start} --> {end}",
            f"F/2.8, SS 50.00, ISO 200, EV +1.0, DZOOM 1.000, GPS (9.6850, 39.9664, 18), "
            f"D 1.76m, H {h:.2f}m, H.S 2.00m/s, V.S 0.00m/s ",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def build(out: Path) -> None:
    """Write the whole fixture set into ``out``."""
    x264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]

    ff(*src(), *x264, str(out / "sharp_pan.mp4"))
    ff(*src(), "-vf", "gblur=sigma=8", *x264, str(out / "blurred.mp4"))
    ff(*src(), "-vf", "eq=brightness=0.6", *x264, str(out / "overexposed.mp4"))
    ff(*src(), "-vf", "eq=brightness=-0.6", *x264, str(out / "underexposed.mp4"))
    ff(*src("smptebars"), *x264, str(out / "static.mp4"))
    ff(
        *src(),
        "-vf",
        "crop=iw-40:ih-40:20+15*sin(t*40):20+15*cos(t*37)",
        *x264,
        str(out / "shaky.mp4"),
    )
    ff(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={SIZE}:rate={FPS}:duration=3",
        "-f",
        "lavfi",
        "-i",
        f"smptebars=size={SIZE}:rate={FPS}:duration=3",
        "-f",
        "lavfi",
        "-i",
        f"mandelbrot=size={SIZE}:rate={FPS}",
        "-filter_complex",
        "[2:v]trim=duration=3,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v]",
        "-map",
        "[v]",
        *x264,
        str(out / "multishot.mp4"),
    )
    # Phones store vertical clips landscape with a rotation side data entry, so the
    # fixture is 640x360 plus rotation -90, exactly like the Xiaomi files. The legacy
    # "-metadata rotate" tag no longer produces a display matrix, hence -display_rotation.
    landscape = out / "vertical_rot90.src.mp4"
    ff(*src(), *x264, str(landscape))
    ff(
        "-display_rotation",
        "-90",
        "-i",
        str(landscape),
        "-c",
        "copy",
        str(out / "vertical_rot90.mp4"),
    )
    landscape.unlink()
    # Export has to prove it removes audio for the classes configured for it and keeps
    # it for the others, and every other fixture is silent, so one clip carries a tone.
    ff(
        *src(),
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=48000:duration={DUR}",
        "-map",
        "0:v",
        "-map",
        "1:a",
        *x264,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out / "with_audio.mp4"),
    )
    # A holiday folder mixes a 4K drone with a 1080p phone, and the export scales down
    # to the maximum without ever scaling up, so the clips come out at different sizes.
    # This is the small one: with it in the edit, the common frame is 320x180 and the
    # 640x360 clips are scaled onto it.
    ff(*src(size="320x180"), *x264, str(out / "small_320.mp4"))
    # The Action 4 shoots 50 fps, which is the case slow motion export exists for: at a
    # 25 fps target the ratio is an exact 2 and no frame has to be invented.
    ff(*src(fps=50), *x264, str(out / "fifty_fps.mp4"))
    ff(
        *src(),
        "-c:v",
        "libx265",
        "-preset",
        "veryfast",
        "-crf",
        "26",
        "-pix_fmt",
        "yuv420p10le",
        "-tag:v",
        "hvc1",
        str(out / "hevc_10bit.mp4"),
    )

    # Beat sync needs a track whose tempo is known exactly, so the fixture is a click
    # at 120 BPM: one beat every 0.5 s. A real Suno track is not reproducible and a
    # sine tone has no onsets for a beat tracker to find.
    ff(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=22050:duration=0.03",
        "-af",
        "apad=whole_dur=0.5,aloop=loop=39:size=11025:start=0",
        "-c:a",
        "pcm_s16le",
        str(out / "click_120bpm.wav"),
    )

    srt = out / "drone_telemetry.srt"
    dji_srt(srt, DUR, heights=[0.5, 1.0, 3.0, 25.0, 30.0, 2.0])
    ff(
        *src(fps=FPS),
        "-i",
        str(srt),
        "-map",
        "0:v",
        "-map",
        "1:s",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "handler_name=DJI.Subtitle",
        *x264,
        str(out / "drone_embedded_srt.mp4"),
    )
    srt.unlink()


def main(argv: list[str] | None = None) -> int:
    force = "--force" in (argv if argv is not None else sys.argv[1:])
    if not force and complete(OUT):
        print(f"fixtures already complete in {OUT}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    # A sibling of OUT, so the moves below stay on one filesystem and are real renames.
    work = Path(tempfile.mkdtemp(dir=OUT.parent, prefix=".synthetic-"))
    try:
        build(work)
        for name in EXPECTED:
            os.replace(work / name, OUT / name)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"fixtures written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

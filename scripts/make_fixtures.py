#!/usr/bin/env python3
"""Generate synthetic, public safe video fixtures into tests/fixtures/synthetic/.

Each fixture exercises one edge case named in SPEC.md section 14. Requires ffmpeg on
PATH. Re-running overwrites. See ADR 8.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic"
SIZE = "640x360"
FPS = 25
DUR = 6


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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    x264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]

    ff(*src(), *x264, str(OUT / "sharp_pan.mp4"))
    ff(*src(), "-vf", "gblur=sigma=8", *x264, str(OUT / "blurred.mp4"))
    ff(*src(), "-vf", "eq=brightness=0.6", *x264, str(OUT / "overexposed.mp4"))
    ff(*src(), "-vf", "eq=brightness=-0.6", *x264, str(OUT / "underexposed.mp4"))
    ff(*src("smptebars"), *x264, str(OUT / "static.mp4"))
    ff(
        *src(),
        "-vf",
        "crop=iw-40:ih-40:20+15*sin(t*40):20+15*cos(t*37)",
        *x264,
        str(OUT / "shaky.mp4"),
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
        str(OUT / "multishot.mp4"),
    )
    # Phones store vertical clips landscape with a rotation side data entry, so the
    # fixture is 640x360 plus rotation -90, exactly like the Xiaomi files. The legacy
    # "-metadata rotate" tag no longer produces a display matrix, hence -display_rotation.
    landscape = OUT / "vertical_rot90.src.mp4"
    ff(*src(), *x264, str(landscape))
    ff(
        "-display_rotation",
        "-90",
        "-i",
        str(landscape),
        "-c",
        "copy",
        str(OUT / "vertical_rot90.mp4"),
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
        str(OUT / "with_audio.mp4"),
    )
    # The Action 4 shoots 50 fps, which is the case slow motion export exists for: at a
    # 25 fps target the ratio is an exact 2 and no frame has to be invented.
    ff(*src(fps=50), *x264, str(OUT / "fifty_fps.mp4"))
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
        str(OUT / "hevc_10bit.mp4"),
    )

    srt = OUT / "drone_telemetry.srt"
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
        str(OUT / "drone_embedded_srt.mp4"),
    )
    srt.unlink()

    print(f"fixtures written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

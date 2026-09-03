"""Output file names and folder layout (SPEC.md section 7.8).

CapCut imports a folder in alphabetical order and offers no way to reorder a bulk
import, so the name has to carry the chronology. A three digit index does that,
and everything after it exists so the file says what it is without being opened.

The date is the local date of the clip. That makes a name depend on the timezone
of the machine that exported it, which is deliberate: the user reads these names
against the days of a holiday, and a clip shot at half past midnight belongs to
the night it was filmed rather than to the UTC day the camera recorded. The only
cost is that re-exporting the same project in another timezone can rename a late
night clip, and a renamed clip is treated as stale rather than lost.
"""

from __future__ import annotations

import re
from pathlib import Path

from autocut.core.manifest import Segment, SourceFile
from autocut.core.select import absolute_time

SELECTS_DIR = "_selects"
REJECTS_DIR = "_rejects"
STALE_DIR = "_stale"
DEFAULT_TAG = "clip"

# Everything outside this set becomes an underscore: these names travel to a Mac,
# to an external disk and into CapCut's own project files.
_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


def sanitize(text: str) -> str:
    """A single name component, safe on every filesystem the output folder crosses."""
    cleaned = _UNSAFE.sub("_", text).strip("_").lower()
    return cleaned or DEFAULT_TAG


def clip_tag(segment: Segment) -> str:
    """The first semantic tag, or the placeholder until tagging lands in M3."""
    return sanitize(segment.tags[0]) if segment.tags else DEFAULT_TAG


def clip_date(segment: Segment, source: SourceFile) -> str:
    """``YYYYMMDD`` of the clip in local time, or zeros when the file has no timestamp."""
    when = absolute_time(source, segment)
    if when is None:
        return "00000000"
    return when.astimezone().strftime("%Y%m%d")


def clip_name(
    segment: Segment,
    source: SourceFile,
    order: int,
    duration_s: float,
    tag: str | None = None,
) -> str:
    """``{index:03d}_{date}_{class}_{tag}_{duration}s.mp4`` for one clip."""
    return (
        f"{order:03d}_{clip_date(segment, source)}_{source.source_class}"
        f"_{sanitize(tag) if tag else clip_tag(segment)}_{duration_s:.1f}s.mp4"
    )


def stale_outputs(selects_dir: Path, expected_names: set[str]) -> list[Path]:
    """Files in ``selects_dir`` that no longer belong to a current clip.

    They are reported rather than removed. A wrong ``select`` run followed by an
    export would otherwise destroy the previous edit, and moving a file aside costs
    nothing next to re-encoding it.
    """
    if not selects_dir.is_dir():
        return []
    return sorted(
        path
        for path in selects_dir.iterdir()
        if path.is_file() and path.name not in expected_names and not path.name.startswith(".")
    )

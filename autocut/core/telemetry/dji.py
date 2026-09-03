"""DJI telemetry: the embedded ``mov_text`` subtitle track and the sidecar ``.SRT``.

The Mini 2 writes one cue per second inside the MP4 (SPEC.md section 4); other
DJI models write the same cue text to a sidecar file. Both adapters share one
parser, and that parser is a regex over ``key value`` pairs so that a firmware
that adds a field keeps working.

A cue looks like::

    F/2.8, SS 50.00, ISO 200, EV +1.0, DZOOM 1.000, GPS (9.6850, 39.9664, 18),
    D 1.76m, H 22.70m, H.S 0.00m/s, V.S -0.00m/s
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from autocut.core.manifest import TelemetryKind
from autocut.core.probe import ProbeResult
from autocut.core.telemetry import TelemetrySample, TelemetrySeries

EXTRACT_TIMEOUT_S = 60.0

# GPS is written longitude first, then latitude, then altitude in metres.
_GPS = re.compile(
    r"GPS\s*\(\s*(?P<lon>[-+]?\d+(?:\.\d+)?)\s*,\s*(?P<lat>[-+]?\d+(?:\.\d+)?)\s*,"
    r"\s*(?P<alt>[-+]?\d+(?:\.\d+)?)\s*\)"
)
# Any "KEY value" pair, so unknown future fields are collected and simply ignored.
_PAIR = re.compile(r"(?P<key>[A-Za-z](?:[A-Za-z.]*[A-Za-z])?)\s+(?P<value>[-+]?\d+(?:\.\d+)?)")
_TIMING = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{1,3})"
)
_MARKUP = re.compile(r"<[^>]+>")

# Cue fields AutoCut understands, mapped onto TelemetrySample field names.
_FLOAT_FIELDS = {
    "H": "height_m",
    "H.S": "speed_h_ms",
    "V.S": "speed_v_ms",
    "SS": "shutter",
    "EV": "ev",
}
# A cue is DJI telemetry when it carries these markers (spec: telemetry-adapters).
_SIGNATURE = ("ISO", "GPS (", "H ")


def looks_like_dji_cue(text: str) -> bool:
    """True when a cue carries the DJI telemetry markers."""
    stripped = _MARKUP.sub(" ", text)
    return sum(marker in stripped for marker in _SIGNATURE) >= 2


def parse_cue(text: str, time_s: float) -> TelemetrySample | None:
    """Parse one cue. Returns ``None`` when nothing recognizable is in it."""
    stripped = _MARKUP.sub(" ", text)
    fields: dict[str, float | int | None] = {}

    gps = _GPS.search(stripped)
    if gps is not None:
        fields["lat"] = float(gps.group("lat"))
        fields["lon"] = float(gps.group("lon"))
        fields["gps_alt_m"] = float(gps.group("alt"))
        stripped = stripped[: gps.start()] + " " + stripped[gps.end() :]

    for match in _PAIR.finditer(stripped):
        key = match.group("key")
        raw = match.group("value")
        if key == "ISO":
            fields["iso"] = int(float(raw))
        elif key in _FLOAT_FIELDS:
            fields[_FLOAT_FIELDS[key]] = float(raw)

    if not fields:
        return None
    return TelemetrySample(time_s=time_s, **fields)


def parse_srt(text: str, kind: TelemetryKind) -> TelemetrySeries:
    """Parse a whole SRT document into a series, skipping cues that make no sense."""
    samples: list[TelemetrySample] = []
    warnings: list[str] = []
    for index, (time_s, cue) in enumerate(_iter_cues(text), start=1):
        sample = parse_cue(cue, time_s)
        if sample is None:
            warnings.append(f"cue {index} could not be parsed")
            continue
        samples.append(sample)
    return TelemetrySeries(kind=kind, samples=samples, warnings=warnings)


def _iter_cues(text: str) -> list[tuple[float, str]]:
    cues: list[tuple[float, str]] = []
    start_s: float | None = None
    body: list[str] = []
    for line in text.splitlines():
        timing = _TIMING.search(line)
        if timing is not None:
            if start_s is not None:
                cues.append((start_s, " ".join(body).strip()))
            start_s = _timecode_seconds(timing.group("start"))
            body = []
            continue
        if start_s is not None and line.strip():
            body.append(line.strip())
    if start_s is not None:
        cues.append((start_s, " ".join(body).strip()))
    return cues


def _timecode_seconds(timecode: str) -> float:
    clock, _, millis = timecode.replace(",", ".").partition(".")
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return hours * 3600 + minutes * 60 + seconds + int(millis.ljust(3, "0")) / 1000.0


def extract_command(path: Path, stream_index: int) -> list[str]:
    """ffmpeg arguments that dump one subtitle stream as SRT without decoding video."""
    return [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        f"0:{stream_index}",
        "-f",
        "srt",
        "-",
    ]


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=EXTRACT_TIMEOUT_S, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


class DjiEmbeddedSrtAdapter:
    """Telemetry carried by a ``mov_text`` subtitle stream inside the MP4."""

    kind: TelemetryKind = "dji_embedded_srt"

    def __init__(self) -> None:
        self._text: dict[Path, str] = {}

    def detect(self, probe: ProbeResult, path: Path) -> bool:
        for stream in probe.subtitle_streams:
            text = self._extract(path, stream.index)
            if text and any(looks_like_dji_cue(cue) for _, cue in _iter_cues(text)[:1]):
                self._text[path] = text
                return True
        return False

    def parse(self, path: Path) -> TelemetrySeries:
        text = self._text.get(path)
        if text is None:
            return TelemetrySeries(kind="dji_embedded_srt")
        return parse_srt(text, "dji_embedded_srt")

    def _extract(self, path: Path, stream_index: int) -> str:
        cached = self._text.get(path)
        if cached is not None:
            return cached
        return _run(extract_command(path, stream_index))


class DjiSidecarSrtAdapter:
    """Telemetry written next to the video as ``<stem>.srt``."""

    kind: TelemetryKind = "dji_sidecar_srt"

    def detect(self, probe: ProbeResult, path: Path) -> bool:
        sidecar = find_sidecar(path)
        if sidecar is None:
            return False
        cues = _iter_cues(_read_text(sidecar))
        return bool(cues) and looks_like_dji_cue(cues[0][1])

    def parse(self, path: Path) -> TelemetrySeries:
        sidecar = find_sidecar(path)
        if sidecar is None:
            return TelemetrySeries(kind="dji_sidecar_srt")
        return parse_srt(_read_text(sidecar), "dji_sidecar_srt")


def find_sidecar(path: Path) -> Path | None:
    """The ``.srt`` next to ``path`` with the same stem, matched case-insensitively."""
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        return None
    stem = path.stem.lower()
    for entry in entries:
        if entry.suffix.lower() == ".srt" and entry.stem.lower() == stem and entry.is_file():
            return entry
    return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

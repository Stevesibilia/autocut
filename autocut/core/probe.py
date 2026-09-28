"""ffprobe based inspection of a single video file.

One ``ffprobe`` call per file, parsed into a typed :class:`ProbeResult`. No
exiftool: every field AutoCut needs is present in ffprobe output on the current
gear (SPEC.md section 4). Failures never raise, they come back as a result with
``error`` set so one unreadable file cannot abort a run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from autocut.core.manifest import GpsPoint, StreamInfo


class ToolMissingError(RuntimeError):
    """A required external binary is not on PATH."""


def require_tools(*names: str) -> None:
    """Raise :class:`ToolMissingError` once, naming every missing binary at once."""
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise ToolMissingError(f"{', '.join(missing)} not found on PATH. Run `autocut doctor`.")


FFPROBE_ARGS: tuple[str, ...] = (
    "-v",
    "error",
    "-print_format",
    "json",
    "-show_format",
    "-show_streams",
)
FFPROBE_TIMEOUT_S = 60.0

# ISO 6709: "+39.9664+9.6850", "+39.9268+009.6641/", optionally with altitude.
_ISO6709 = re.compile(
    r"^(?P<lat>[+-]\d+(?:\.\d+)?)(?P<lon>[+-]\d+(?:\.\d+)?)(?P<alt>[+-]\d+(?:\.\d+)?)?/?$"
)
# Bit depth carried by the pixel format name: yuv420p10le -> 10, yuv420p -> absent.
_PIX_FMT_DEPTH = re.compile(r"p(\d{1,2})(?:le|be)?$")

# Format tag keys that name the manufacturer and the model, in priority order.
_MAKE_KEYS = ("make", "com.apple.quicktime.make", "com.android.manufacturer", "manufacturer")
_MODEL_KEYS = (
    "model",
    "com.apple.quicktime.model",
    "com.android.model",
    "com.xiaomi.product.marketname",
)
_ENCODER_KEYS = ("encoder", "com.apple.quicktime.software", "software")

ANDROID_MAKE_KEY = "com.android.manufacturer"
APPLE_MAKE_KEY = "com.apple.quicktime.make"


def ffprobe_command(path: Path) -> list[str]:
    """Argument list for probing ``path``. Built as a list, never a shell string."""
    return ["ffprobe", *FFPROBE_ARGS, str(path)]


class ProbeResult(BaseModel):
    """Everything one ffprobe call tells us about a file."""

    path: Path
    error: str | None = None
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    rotation: int = 0
    fps: float = 0.0
    codec: str = ""
    pix_fmt: str = ""
    bit_depth: int = 8
    color_transfer: str | None = None
    creation_time: datetime | None = None
    creation_time_raw: str | None = None
    make: str | None = None
    model: str | None = None
    encoder: str | None = None
    gps: GpsPoint | None = None
    format_tags: dict[str, str] = Field(default_factory=dict)
    video_tags: dict[str, str] = Field(default_factory=dict)
    subtitle_streams: list[StreamInfo] = Field(default_factory=list)
    data_streams: list[StreamInfo] = Field(default_factory=list)
    has_audio: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def display_width(self) -> int:
        return self.height if self.rotation % 180 == 90 else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation % 180 == 90 else self.height

    @property
    def is_vertical(self) -> bool:
        """Orientation as the viewer sees it, rotation side data applied."""
        return self.display_height > self.display_width


def probe_file(path: Path, *, timeout_s: float = FFPROBE_TIMEOUT_S) -> ProbeResult:
    """Probe ``path`` with ffprobe. Never raises: errors land in ``ProbeResult.error``."""
    try:
        completed = subprocess.run(
            ffprobe_command(path),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return ProbeResult(path=path, error="ffprobe not found on PATH")
    except subprocess.TimeoutExpired:
        return ProbeResult(path=path, error=f"ffprobe timed out after {timeout_s:g}s")
    if completed.returncode != 0:
        return ProbeResult(path=path, error=_first_line(completed.stderr) or "ffprobe failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return ProbeResult(path=path, error=f"unreadable ffprobe output: {exc}")
    return parse_probe_json(path, payload)


def parse_probe_json(path: Path, payload: dict[str, Any]) -> ProbeResult:
    """Turn raw ffprobe JSON into a :class:`ProbeResult`. Pure, so it is unit testable."""
    streams: list[dict[str, Any]] = list(payload.get("streams") or [])
    fmt: dict[str, Any] = dict(payload.get("format") or {})
    format_tags = _string_tags(fmt.get("tags"))

    video = _primary_video(streams)
    if video is None:
        return ProbeResult(
            path=path,
            error="no video stream",
            format_tags=format_tags,
            subtitle_streams=_stream_infos(streams, "subtitle"),
            data_streams=_stream_infos(streams, "data"),
        )

    video_tags = _string_tags(video.get("tags"))
    creation_raw = video_tags.get("creation_time") or format_tags.get("creation_time")
    pix_fmt = str(video.get("pix_fmt") or "")

    return ProbeResult(
        path=path,
        duration_s=_duration(fmt, video),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        rotation=_rotation(video),
        fps=_frame_rate(video),
        codec=str(video.get("codec_name") or ""),
        pix_fmt=pix_fmt,
        bit_depth=_bit_depth(pix_fmt, video.get("bits_per_raw_sample")),
        color_transfer=_optional_str(video.get("color_transfer")),
        creation_time=_parse_time(creation_raw),
        creation_time_raw=creation_raw,
        make=_first_tag(format_tags, video_tags, keys=_MAKE_KEYS),
        model=_first_tag(format_tags, video_tags, keys=_MODEL_KEYS),
        encoder=_first_tag(format_tags, video_tags, keys=_ENCODER_KEYS),
        gps=_gps(format_tags),
        format_tags=format_tags,
        video_tags=video_tags,
        subtitle_streams=_stream_infos(streams, "subtitle"),
        data_streams=_stream_infos(streams, "data"),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


# Some Osmo Action 4 clips carry an mjpeg thumbnail as a second video stream.
_COVER_CODECS = frozenset({"mjpeg", "png", "bmp", "gif"})


def _primary_video(streams: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The real picture stream, ignoring embedded cover art and thumbnails."""
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if not videos:
        return None
    for stream in videos:
        disposition = stream.get("disposition") or {}
        if disposition.get("attached_pic"):
            continue
        if str(stream.get("codec_name") or "") in _COVER_CODECS and len(videos) > 1:
            continue
        return stream
    return videos[0]


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _optional_str(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return text or None


def _string_tags(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _stream_infos(streams: list[dict[str, Any]], codec_type: str) -> list[StreamInfo]:
    infos: list[StreamInfo] = []
    for stream in streams:
        if stream.get("codec_type") != codec_type:
            continue
        tags = _string_tags(stream.get("tags"))
        infos.append(
            StreamInfo(
                index=int(stream.get("index") or 0),
                codec_type=codec_type,
                codec_name=_optional_str(stream.get("codec_name")),
                codec_tag=_optional_str(stream.get("codec_tag_string")),
                handler_name=_optional_str(tags.get("handler_name")),
                language=_optional_str(tags.get("language")),
            )
        )
    return infos


def _duration(fmt: dict[str, Any], video: dict[str, Any]) -> float:
    candidates: tuple[Any, ...] = (fmt.get("duration"), video.get("duration"))
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def _frame_rate(video: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        rate = str(video.get(key) or "")
        if "/" not in rate:
            continue
        num, _, den = rate.partition("/")
        try:
            numerator, denominator = float(num), float(den)
        except ValueError:
            continue
        if denominator > 0 and numerator > 0:
            return numerator / denominator
    return 0.0


def _rotation(video: dict[str, Any]) -> int:
    """Rotation in the ffprobe side data convention, normalized to (-180, 180]."""
    for entry in video.get("side_data_list") or []:
        if isinstance(entry, dict) and entry.get("rotation") is not None:
            try:
                return _normalize_angle(float(entry["rotation"]))
            except (TypeError, ValueError):
                continue
    legacy = _string_tags(video.get("tags")).get("rotate")
    if legacy:
        try:
            # The legacy tag is the clockwise angle to apply, the opposite sign of side data.
            return _normalize_angle(-float(legacy))
        except ValueError:
            return 0
    return 0


def _normalize_angle(angle: float) -> int:
    normalized = int(round(angle)) % 360
    return normalized - 360 if normalized > 180 else normalized


def _bit_depth(pix_fmt: str, bits_per_raw_sample: Any) -> int:
    match = _PIX_FMT_DEPTH.search(pix_fmt)
    if match:
        return int(match.group(1))
    try:
        depth = int(bits_per_raw_sample)
    except (TypeError, ValueError):
        return 8
    return depth if depth > 0 else 8


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _first_tag(*tag_sets: dict[str, str], keys: tuple[str, ...]) -> str | None:
    lowered = [{k.lower(): v for k, v in tags.items()} for tags in tag_sets]
    for key in keys:
        for tags in lowered:
            value = tags.get(key)
            if value and value.strip():
                return value.strip()
    return None


def _gps(format_tags: dict[str, str]) -> GpsPoint | None:
    for key, value in format_tags.items():
        # Devices write "location", "location-eng" and, on the Mini 2, "location-{".
        if not key.lower().startswith("location"):
            continue
        match = _ISO6709.match(value.strip())
        if not match:
            continue
        altitude = match.group("alt")
        return GpsPoint(
            lat=float(match.group("lat")),
            lon=float(match.group("lon")),
            alt_m=float(altitude) if altitude else None,
        )
    return None

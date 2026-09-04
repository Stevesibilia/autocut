"""Global analysis cache (ADR 6).

Entries live outside any project so a second project on the same footage, or a
project deleted by mistake, never triggers a re-analysis. The key carries the
analysis schema version and the sampling parameters, so changing either simply
misses and the entry is recomputed rather than silently reused.

Each entry is one ``.npz`` with the metric arrays, the thumbnail frames and the
segment embeddings, plus one ``.json`` with the probe result, telemetry samples, shot
bounds and the identifier of the model the embeddings came from. Writes go to a
temporary file and are renamed into place, so an interrupted run never leaves a half
written entry behind.

Embeddings are versioned by model identifier rather than by the analysis schema: a
different model has to be recomputed, but the metric arrays it sits beside cost a
decode and stay valid, so a model change must not throw them away.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from platformdirs import user_cache_dir

from autocut.core.config import AutocutConfig
from autocut.core.manifest import ANALYSIS_SCHEMA_VERSION

ARRAY_NAMES = ("timestamps", "sharpness", "clipping", "motion", "stability", "colorfulness")


@dataclass(slots=True)
class CacheEntry:
    """Everything analysis learned about one file, minus the project specific parts."""

    file_key: str
    source: str
    arrays: dict[str, np.ndarray]
    shot_bounds: list[tuple[float, float]]
    telemetry: list[dict[str, Any]] = field(default_factory=list)
    probe: dict[str, Any] = field(default_factory=dict)
    thumb_frames: np.ndarray | None = None
    sprites: list[np.ndarray] = field(default_factory=list)
    embeddings: np.ndarray | None = None
    embedding_model: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        timestamps = self.arrays.get("timestamps")
        return int(timestamps.shape[0]) if timestamps is not None else 0


def cache_dir(config: AutocutConfig) -> Path:
    """The configured cache directory, or the platform one, created on first use."""
    base = config.cache.dir or Path(user_cache_dir("autocut"))
    directory = base / f"v{ANALYSIS_SCHEMA_VERSION}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def entry_name(file_key: str, config: AutocutConfig) -> str:
    """Entry stem: the file key plus the sampling parameters it was computed with."""
    fps = f"{config.analysis.sample_fps:g}".replace(".", "-")
    return f"{file_key}_{fps}_{config.analysis.sample_long_side}"


def entry_path(file_key: str, config: AutocutConfig) -> Path:
    return cache_dir(config) / f"{entry_name(file_key, config)}.npz"


def thumb_index(segment_id: str, count: int) -> int:
    """Which cached frame belongs to a segment, or ``-1`` when the entry holds none.

    One frame is cached per detected shot, and a segment is a span of a shot: an
    altitude split makes two segments out of one shot and both describe the same frame.
    The index is therefore the segment's suffix clamped into the array, and every
    consumer of the frames, the hashes and the embeddings has to agree on it or a
    similarity would compare one shot's thumbnail with another shot's vector.
    """
    if count <= 0:
        return -1
    _, _, suffix = segment_id.rpartition(":")
    try:
        index = int(suffix)
    except ValueError:
        index = 0
    return min(max(index, 0), count - 1)


def shot_index(shot_bounds: list[tuple[float, float]], start_s: float) -> int:
    """Index of the detected shot a span came from. Splits share their shot's frames.

    Here beside ``thumb_index`` because both answer the same question, which cached
    picture belongs to a segment, and both have to give the same answer to every
    consumer: the thumbnails, the sprite strips and the embeddings are indexed by shot.
    """
    for index, (start, stop) in enumerate(shot_bounds):
        if start <= start_s < stop:
            return index
    return max(len(shot_bounds) - 1, 0)


def read_entry(file_key: str, config: AutocutConfig, sprites: bool = True) -> CacheEntry | None:
    """Load an entry, or ``None`` when it is missing, stale or unreadable.

    An entry whose embeddings were computed with another model comes back with none,
    because the vectors are not comparable, while its metric arrays are handed over
    untouched.

    ``sprites`` exists because they are most of the file and almost nobody wants them.
    A strip is every sampled frame of a shot, so an entry with sprites is megabytes
    where the metric arrays are kilobytes, and decompressing them is what a caller
    pays for asking. Selection reads every entry in the project on every run, which is
    what the review sliders do on every move: measured on the Sardinia folder, leaving
    the strips in the file took a re-selection from 1.5 s to under half a second.
    """
    arrays_path = entry_path(file_key, config)
    meta_path = arrays_path.with_suffix(".json")
    if not arrays_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        with np.load(arrays_path) as payload:
            arrays = {name: payload[name] for name in ARRAY_NAMES if name in payload}
            thumbs = payload.get("thumb_frames")
            embeddings = payload.get("embeddings")
            strips = (
                [
                    payload[name]
                    for name in sorted(
                        (n for n in payload.files if n.startswith("sprite_")),
                        key=lambda n: int(n.split("_")[1]),
                    )
                ]
                if sprites
                else []
            )
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    if meta.get("analysis_schema_version") != ANALYSIS_SCHEMA_VERSION:
        return None
    embedding_model = meta.get("embedding_model")
    if embedding_model != config.providers.embedding_model:
        embeddings, embedding_model = None, None
    return CacheEntry(
        file_key=file_key,
        source=str(meta.get("source", "original")),
        arrays=arrays,
        shot_bounds=[(float(a), float(b)) for a, b in meta.get("shot_bounds", [])],
        telemetry=list(meta.get("telemetry", [])),
        probe=dict(meta.get("probe", {})),
        thumb_frames=thumbs,
        sprites=strips,
        embeddings=embeddings,
        embedding_model=embedding_model,
        warnings=list(meta.get("warnings", [])),
    )


def write_entry(entry: CacheEntry, config: AutocutConfig) -> Path:
    """Write an entry atomically and return the arrays path."""
    arrays_path = entry_path(entry.file_key, config)
    meta_path = arrays_path.with_suffix(".json")
    payload: dict[str, np.ndarray] = dict(entry.arrays)
    if entry.thumb_frames is not None:
        payload["thumb_frames"] = entry.thumb_frames
    if entry.embeddings is not None:
        payload["embeddings"] = entry.embeddings
    for index, sprite in enumerate(entry.sprites):
        payload[f"sprite_{index}"] = sprite

    tmp_arrays = arrays_path.with_suffix(".npz.tmp")
    tmp_meta = meta_path.with_suffix(".json.tmp")
    with tmp_arrays.open("wb") as handle:
        # The stub types the second positional parameter as "allow_pickle", so the
        # keyword-array form has to be spelled out for the type checker.
        np.savez_compressed(handle, **payload)  # type: ignore[arg-type]
    tmp_meta.write_text(
        json.dumps(
            {
                "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
                "file_key": entry.file_key,
                "source": entry.source,
                "sample_fps": config.analysis.sample_fps,
                "sample_long_side": config.analysis.sample_long_side,
                "shot_bounds": [[a, b] for a, b in entry.shot_bounds],
                "embedding_model": entry.embedding_model,
                "telemetry": entry.telemetry,
                "probe": entry.probe,
                "warnings": entry.warnings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp_arrays.replace(arrays_path)
    tmp_meta.replace(meta_path)
    return arrays_path


@dataclass(slots=True)
class CacheStats:
    directory: Path
    entries: int
    bytes: int

    @property
    def megabytes(self) -> float:
        return self.bytes / (1024 * 1024)


def cache_stats(config: AutocutConfig) -> CacheStats:
    """Entry count and total size of the cache directory."""
    directory = cache_dir(config)
    entries = sorted(directory.glob("*.npz"))
    total = 0
    for path in directory.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return CacheStats(directory=directory, entries=len(entries), bytes=total)


def prune(config: AutocutConfig, older_than_days: float) -> int:
    """Delete entries not modified for ``older_than_days``. Returns the count removed."""
    directory = cache_dir(config)
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for arrays_path in sorted(directory.glob("*.npz")):
        if arrays_path.stat().st_mtime >= cutoff:
            continue
        arrays_path.unlink(missing_ok=True)
        arrays_path.with_suffix(".json").unlink(missing_ok=True)
        removed += 1
    return removed


def clear(config: AutocutConfig) -> None:
    """Remove the whole cache directory for the current schema version."""
    shutil.rmtree(cache_dir(config), ignore_errors=True)

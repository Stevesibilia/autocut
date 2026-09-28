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
import os
import shutil
import threading
import time
import uuid
from collections import OrderedDict
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
    derived: dict[str, Any] = field(default_factory=dict)
    """Values computed from this entry, such as a segment's visual hashes. Memory only,
    never written by :func:`write_entry` (design decision 5, issue #82)."""

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
            npz_token_array = payload.get("write_token")
            npz_token = str(npz_token_array.item()) if npz_token_array is not None else None
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
    except Exception:  # noqa: BLE001 - any unreadable entry is a miss by contract, see decision 5
        return None
    if meta.get("analysis_schema_version") != ANALYSIS_SCHEMA_VERSION:
        return None
    if meta.get("file_key") != file_key:
        return None
    json_token = meta.get("write_token")
    if (npz_token is None) != (json_token is None):
        return None
    if npz_token is not None and json_token is not None and npz_token != json_token:
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


_MemoryKey = tuple[str, int, int, int, str | None]

# In-process, read-only LRU of recently read entries (design decision 5, issue #82).
# Keyed by the arrays path so a stale entry for a rewritten or deleted file is found
# and dropped even when it no longer matches the current stat.
_memory_cache: OrderedDict[str, tuple[_MemoryKey, CacheEntry]] = OrderedDict()
_memory_lock = threading.Lock()


def _memory_key(arrays_path: Path, meta_path: Path, config: AutocutConfig) -> _MemoryKey | None:
    """One ``stat`` of each file, plus the embedding model. ``None`` when either is missing."""
    try:
        npz_stat = arrays_path.stat()
        json_stat = meta_path.stat()
    except OSError:
        return None
    return (
        str(arrays_path),
        npz_stat.st_mtime_ns,
        npz_stat.st_size,
        json_stat.st_mtime_ns,
        config.providers.embedding_model,
    )


def _freeze(entry: CacheEntry) -> CacheEntry:
    """Mark every array on ``entry`` read-only, so a shared cache hit cannot be mutated."""
    for array in entry.arrays.values():
        array.flags.writeable = False
    if entry.thumb_frames is not None:
        entry.thumb_frames.flags.writeable = False
    if entry.embeddings is not None:
        entry.embeddings.flags.writeable = False
    return entry


def read_entry_cached(file_key: str, config: AutocutConfig) -> CacheEntry | None:
    """``read_entry(..., sprites=False)`` behind an in-process, read-only LRU.

    Selection reads every candidate's entry on every run, which is what the review
    sliders trigger on every move. This keeps up to ``config.cache.memory_entries``
    entries in memory, keyed on one ``stat`` of each file and the embedding model,
    so a rewritten or deleted entry misses instead of returning stale arrays. A
    hit's arrays are shared with every caller, so they come back read-only; write
    through :func:`write_entry` instead of mutating one. ``memory_entries = 0``
    disables the cache and reads from disk every time.
    """
    arrays_path = entry_path(file_key, config)
    meta_path = arrays_path.with_suffix(".json")
    path_key = str(arrays_path)
    current = _memory_key(arrays_path, meta_path, config)

    with _memory_lock:
        cached = _memory_cache.get(path_key)
        if cached is not None and cached[0] == current:
            _memory_cache.move_to_end(path_key)
            return cached[1]
        if cached is not None:
            del _memory_cache[path_key]

    if current is None:
        return None

    entry = read_entry(file_key, config, sprites=False)
    if entry is None:
        return None
    _freeze(entry)

    limit = config.cache.memory_entries
    if limit <= 0:
        return entry
    with _memory_lock:
        _memory_cache[path_key] = (current, entry)
        _memory_cache.move_to_end(path_key)
        while len(_memory_cache) > limit:
            _memory_cache.popitem(last=False)
    return entry


def write_entry(entry: CacheEntry, config: AutocutConfig) -> Path:
    """Write an entry atomically and return the arrays path.

    The arrays file and the metadata file are written under one shared write token
    (decision 5), so a reader that sees them written by two different calls, such as
    two processes racing on the same key, can tell and treat the entry as a miss
    instead of pairing new arrays with old metadata or the reverse.
    """
    arrays_path = entry_path(entry.file_key, config)
    meta_path = arrays_path.with_suffix(".json")
    token = uuid.uuid4().hex
    payload: dict[str, np.ndarray] = dict(entry.arrays)
    payload["write_token"] = np.array(token)
    if entry.thumb_frames is not None:
        payload["thumb_frames"] = entry.thumb_frames
    if entry.embeddings is not None:
        payload["embeddings"] = entry.embeddings
    for index, sprite in enumerate(entry.sprites):
        payload[f"sprite_{index}"] = sprite

    # PID qualified, so two writers on the same key never share a temporary file.
    tmp_arrays = arrays_path.with_name(f"{arrays_path.stem}.{os.getpid()}.npz.tmp")
    tmp_meta = meta_path.with_name(f"{meta_path.stem}.{os.getpid()}.json.tmp")
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
                "write_token": token,
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
    """Delete entries not modified for ``older_than_days``. Returns the count removed.

    Also sweeps orphaned metadata files (an interrupted write, or a since-deleted
    arrays file) and leftover ``.tmp`` files, when they are old enough too. Neither
    counts toward the returned total, which stays the number of entries removed.
    """
    directory = cache_dir(config)
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for arrays_path in sorted(directory.glob("*.npz")):
        if arrays_path.stat().st_mtime >= cutoff:
            continue
        arrays_path.unlink(missing_ok=True)
        arrays_path.with_suffix(".json").unlink(missing_ok=True)
        removed += 1

    remaining_stems = {path.stem for path in directory.glob("*.npz")}
    for meta_path in sorted(directory.glob("*.json")):
        if meta_path.stem in remaining_stems:
            continue
        if meta_path.stat().st_mtime >= cutoff:
            continue
        meta_path.unlink(missing_ok=True)

    for tmp_path in sorted(directory.glob("*.tmp")):
        if tmp_path.stat().st_mtime >= cutoff:
            continue
        tmp_path.unlink(missing_ok=True)

    return removed


def clear(config: AutocutConfig) -> None:
    """Remove the whole cache directory for the current schema version."""
    shutil.rmtree(cache_dir(config), ignore_errors=True)

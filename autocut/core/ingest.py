"""Scan source folders, probe every file and order the result chronologically.

Probing and telemetry extraction are subprocess bound, so files are handled by a
thread pool sized on physical cores: each worker mostly waits on ffprobe, a
subtitle extract, a hash read and a directory listing, and threads share the
interpreter that a spawned process would otherwise re-import numpy, cv2 and
pydantic into. The worker stays a module level function so it stays picklable,
which the pool no longer needs but a test still asserts (issue #82).
"""

from __future__ import annotations

import functools
import os
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath

from autocut.core.cachekey import cache_key
from autocut.core.classify import classify
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.manifest import SourceFile, TelemetryKind
from autocut.core.probe import probe_file
from autocut.core.proc import require_tools
from autocut.core.telemetry import TelemetrySeries, detect_telemetry

ACCEPTED_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".m4v", ".insv"})
PROXY_EXTENSIONS = frozenset({".lrv", ".lrf"})
SKIPPED_EXTENSIONS = frozenset({".part"})


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """A file found by the scan, with the source folder it came from."""

    path: Path
    source_root: Path

    @property
    def rel_path(self) -> PurePath:
        try:
            return PurePath(self.path.relative_to(self.source_root))
        except ValueError:
            return PurePath(self.path.name)


@functools.cache
def physical_cores() -> int:
    """Physical core count, falling back to the logical count then to one.

    Cached: the ``sysctl``/``/proc/cpuinfo`` probe is shelled out or read once
    per process, not once per pool created (design decision 2, issue #82).
    """
    if platform.system() == "Darwin":
        try:
            output = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
            if output.isdigit() and int(output) > 0:
                return int(output)
        except (OSError, subprocess.SubprocessError):
            pass
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            cores: set[tuple[str, str]] = set()
            physical_id = core_id = ""
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, value = line.partition(":")
                key, value = key.strip(), value.strip()
                if key == "physical id":
                    physical_id = value
                elif key == "core id":
                    core_id = value
                    cores.add((physical_id, core_id))
            if cores:
                return len(cores)
        except OSError:
            pass
    return os.cpu_count() or 1


def scan(sources: list[Path], config: AutocutConfig | None = None) -> list[ScannedFile]:
    """Collect accepted video files under ``sources``, recursively and deterministically."""
    del config  # Accepted for symmetry with the rest of the API; nothing to tune yet.
    found: dict[Path, ScannedFile] = {}
    for source in sources:
        root = source.resolve()
        if root.is_file():
            if _is_accepted(root, root.parent):
                found.setdefault(root, ScannedFile(path=root, source_root=root.parent))
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and _is_accepted(path, root):
                found.setdefault(path, ScannedFile(path=path, source_root=root))
    return sorted(found.values(), key=lambda item: item.path)


def _is_accepted(path: Path, root: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in PROXY_EXTENSIONS or suffix in SKIPPED_EXTENSIONS:
        return False
    if suffix not in ACCEPTED_EXTENSIONS:
        return False
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = (path.name,)
    return not any(part.startswith(".") for part in parts)


def find_proxy(path: Path, config: AutocutConfig | None = None) -> Path | None:
    """The ``.lrv`` or ``.lrf`` sharing the stem of ``path``, matched case-insensitively."""
    if config is not None and not config.analysis.use_proxies:
        return None
    try:
        entries = sorted(path.parent.iterdir())
    except OSError:
        return None
    stem = path.stem.lower()
    for entry in entries:
        if (
            entry.suffix.lower() in PROXY_EXTENSIONS
            and entry.stem.lower() == stem
            and entry.is_file()
        ):
            return entry
    return None


def ingest_file(scanned: ScannedFile, config: AutocutConfig) -> SourceFile:
    """Probe, detect telemetry, classify and key one file. Runs inside a pool worker."""
    path = scanned.path
    probe = probe_file(path)
    telemetry_kind: TelemetryKind = "none"
    series: TelemetrySeries | None = None
    if probe.ok:
        telemetry_kind, series = detect_telemetry(probe, path)
    classification = classify(
        probe, telemetry_kind, scanned.rel_path, config.analysis.class_overrides
    )
    return SourceFile(
        id=cache_key(path) or f"path:{path}",
        path=path,
        proxy_path=find_proxy(path, config),
        source_class=classification.source_class,
        class_signal=classification.signal,
        class_overridden=classification.overridden,
        duration_s=probe.duration_s,
        width=probe.width,
        height=probe.height,
        rotation=probe.rotation,
        fps=probe.fps,
        codec=probe.codec,
        pix_fmt=probe.pix_fmt,
        bit_depth=probe.bit_depth,
        creation_time=probe.creation_time,
        make=probe.make,
        model=probe.model,
        gps=probe.gps,
        telemetry=telemetry_kind,
        telemetry_summary=series.summary() if series is not None else None,
        subtitle_streams=probe.subtitle_streams,
        data_streams=probe.data_streams,
        error=probe.error,
    )


def ingest(
    sources: list[Path],
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
) -> list[SourceFile]:
    """Ingest every accepted file under ``sources``, ordered chronologically."""
    scanned = scan(sources, config)
    total = len(scanned)
    progress(ProgressEvent(stage="scan", current=total, total=total))
    if not scanned:
        return []
    require_tools("ffprobe", "ffmpeg")

    workers = max(1, config.analysis.workers or physical_cores())
    results: dict[Path, SourceFile] = {}
    if workers == 1 or total == 1:
        for index, item in enumerate(scanned, start=1):
            try:
                results[item.path] = ingest_file(item, config)
            except Exception as exc:  # noqa: BLE001 - becomes this file's error, see decision 2
                results[item.path] = _failed_source(item, exc)
            progress(ProgressEvent(stage="probe", current=index, total=total, path=item.path))
    else:
        with ThreadPoolExecutor(max_workers=min(workers, total)) as pool:
            futures = {pool.submit(ingest_file, item, config): item for item in scanned}
            for index, future in enumerate(as_completed(futures), start=1):
                item = futures[future]
                try:
                    results[item.path] = future.result()
                except Exception as exc:  # noqa: BLE001 - see decision 2
                    results[item.path] = _failed_source(item, exc)
                progress(ProgressEvent(stage="probe", current=index, total=total, path=item.path))

    return sorted(results.values(), key=_chronological_key)


def _failed_source(item: ScannedFile, exc: Exception) -> SourceFile:
    return SourceFile(
        id=cache_key(item.path) or f"path:{item.path}",
        path=item.path,
        error=f"worker failed: {exc}",
    )


def _chronological_key(source: SourceFile) -> tuple[datetime, str]:
    """Creation time, falling back to mtime, with the path breaking ties."""
    created = source.creation_time
    if created is None:
        try:
            created = datetime.fromtimestamp(source.path.stat().st_mtime, tz=UTC)
        except OSError:
            created = datetime.fromtimestamp(0, tz=UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created, str(source.path)

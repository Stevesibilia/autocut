"""Analysis orchestration: from a manifest of files to scored segments.

Per-file work (decode, shot detection, metrics) runs in a process pool and is
cached globally. Normalization and scoring happen in the parent once every file
is in, because normalization is project wide and cannot be done a file at a time.

The progress callback may raise :class:`AnalysisCancelled`. The orchestrator
catches it between files, stops consuming results, writes what it has and
re-raises so the front end can report a clean stop.
"""

from __future__ import annotations

import multiprocessing
import signal
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from autocut.core.cache import CacheEntry, read_entry, shot_index, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.hwaccel import SOFTWARE, Hwaccel
from autocut.core.hwaccel import select as select_hwaccel
from autocut.core.hwaccel import verify as verify_hwaccel
from autocut.core.ingest import physical_cores
from autocut.core.manifest import AnalysisRun, Manifest, Metrics, Segment, SourceFile
from autocut.core.metrics import frame_metrics
from autocut.core.probe import ProbeResult, probe_from_source
from autocut.core.rules import apply_rules
from autocut.core.sampler import sample_frames
from autocut.core.score import score_metrics
from autocut.core.segment import (
    apply_trims,
    detect_shots,
    detect_shots_pyscenedetect,
    split_on_altitude,
)
from autocut.core.telemetry import TelemetrySample, detect_telemetry
from autocut.core.thumbs import build_sprite, write_sprite, write_thumbnail


class AnalysisCancelled(Exception):  # noqa: N818 - a cancellation, not an error
    """Raised by a progress callback to stop analysis between files."""


def _ignore_sigint() -> None:
    """Pool initializer: workers let their ffmpeg children take Ctrl-C, not print their own."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


@dataclass(slots=True)
class FileAnalysis:
    """What one worker learned about one file."""

    file_id: str
    entry: CacheEntry | None = None
    cached: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def analyze_file(
    source: SourceFile, config: AutocutConfig, hwaccel: Hwaccel = SOFTWARE
) -> FileAnalysis:
    """Decode, detect shots and measure one file. Runs inside a pool worker."""
    cached = read_entry(source.id, config)
    if cached is not None:
        return FileAnalysis(file_id=source.id, entry=cached, cached=True)

    probe = probe_from_source(source)
    if not probe.ok:
        return FileAnalysis(file_id=source.id, error=probe.error)

    sampled = sample_frames(source.path, probe, config, source.proxy_path, hwaccel)
    if sampled.count == 0:
        return FileAnalysis(
            file_id=source.id,
            error="no frames decoded",
            warnings=sampled.warnings,
        )

    metrics = frame_metrics(
        sampled.frames,
        source.source_class,
        center_crop_fraction=config.analysis.sharpness_center_crop,
        stability_window=config.analysis.stability_window,
    )
    bounds = _shot_bounds(sampled.frames, sampled.timestamps, probe, source, config)

    entry = CacheEntry(
        file_key=source.id,
        source=sampled.source,
        arrays={
            "timestamps": sampled.timestamps,
            "sharpness": metrics.sharpness,
            "clipping": metrics.clipping,
            "motion": metrics.motion,
            "stability": metrics.stability,
            "colorfulness": metrics.colorfulness,
        },
        shot_bounds=bounds,
        telemetry=_telemetry_payload(probe, source),
        probe=probe.model_dump(mode="json"),
        thumb_frames=_thumb_frames(sampled.frames, sampled.timestamps, bounds),
        sprites=_sprites(sampled.frames, sampled.timestamps, bounds, config),
        warnings=sampled.warnings,
    )
    write_entry(entry, config)
    return FileAnalysis(file_id=source.id, entry=entry, warnings=sampled.warnings)


def _shot_bounds(
    frames: np.ndarray,
    timestamps: np.ndarray,
    probe: ProbeResult,
    source: SourceFile,
    config: AutocutConfig,
) -> list[tuple[float, float]]:
    duration = probe.duration_s or source.duration_s
    if config.analysis.detector == "pyscenedetect":
        target = source.proxy_path if source.proxy_path and config.analysis.use_proxies else None
        min_len_frames = max(1, int(round(config.analysis.min_scene_seconds * (probe.fps or 25))))
        bounds = detect_shots_pyscenedetect(
            target or source.path, config.analysis.scene_threshold, min_len_frames
        )
        return bounds or [(0.0, duration)]
    return detect_shots(
        frames,
        timestamps,
        config.analysis.scene_threshold,
        config.analysis.min_scene_seconds,
        duration,
    )


def _telemetry_payload(probe: ProbeResult, source: SourceFile) -> list[dict[str, object]]:
    if source.telemetry == "none":
        return []
    _, series = detect_telemetry(probe, source.path)
    if series is None:
        return []
    return [sample.model_dump(mode="json") for sample in series.samples]


def _frames_in(timestamps: np.ndarray, start: float, stop: float) -> np.ndarray:
    return np.flatnonzero((timestamps >= start) & (timestamps < stop))


def _thumb_frames(
    frames: np.ndarray, timestamps: np.ndarray, bounds: list[tuple[float, float]]
) -> np.ndarray:
    """One frame per shot, the sampled frame closest to the shot midpoint."""
    picks: list[np.ndarray] = []
    for start, stop in bounds:
        midpoint = (start + stop) / 2
        index = int(np.argmin(np.abs(timestamps - midpoint))) if timestamps.size else 0
        picks.append(frames[index] if frames.shape[0] else np.zeros((1, 1, 3), dtype=np.uint8))
    return np.stack(picks) if picks else np.zeros((0, 1, 1, 3), dtype=np.uint8)


def _sprites(
    frames: np.ndarray,
    timestamps: np.ndarray,
    bounds: list[tuple[float, float]],
    config: AutocutConfig,
) -> list[np.ndarray]:
    if not config.analysis.sprites:
        return []
    sprites: list[np.ndarray] = []
    for start, stop in bounds:
        indices = _frames_in(timestamps, start, stop)
        chosen = frames[indices] if indices.size else frames[:1]
        sprites.append(build_sprite(chosen, config.analysis.sprite_max_frames))
    return sprites


def analyze_files(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
) -> None:
    """Analyze every probed file in ``manifest`` and fill in its segments."""
    pending = [source for source in manifest.files.values() if source.error is None]
    total = len(pending)
    if total == 0:
        return

    results: dict[str, FileAnalysis] = {}
    workers = max(1, config.analysis.workers or physical_cores())
    cancelled: AnalysisCancelled | None = None
    hwaccel, hwaccel_warnings = choose_hwaccel(config, pending)

    if workers == 1 or total == 1:
        try:
            for index, source in enumerate(pending, start=1):
                try:
                    results[source.id] = analyze_file(source, config, hwaccel)
                except Exception as exc:  # noqa: BLE001 - becomes this file's error, see decision 2
                    results[source.id] = FileAnalysis(
                        file_id=source.id, error=f"worker failed: {exc}"
                    )
                try:
                    progress(_event(index, total, source, results[source.id]))
                except AnalysisCancelled as exc:
                    cancelled = exc
                    break
        except KeyboardInterrupt:
            cancelled = AnalysisCancelled("interrupted")
    else:
        futures: dict[Future[FileAnalysis], SourceFile] = {}
        try:
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=min(workers, total), mp_context=context, initializer=_ignore_sigint
            ) as pool:
                futures = {
                    pool.submit(analyze_file, source, config, hwaccel): source for source in pending
                }
                for done, future in enumerate(as_completed(futures), start=1):
                    source = futures[future]
                    try:
                        results[source.id] = future.result()
                    except Exception as exc:  # noqa: BLE001 - see decision 2
                        results[source.id] = FileAnalysis(
                            file_id=source.id, error=f"worker failed: {exc}"
                        )
                    try:
                        progress(_event(done, total, source, results[source.id]))
                    except AnalysisCancelled as exc:
                        cancelled = exc
                        for other in futures:
                            other.cancel()
                        break
        except KeyboardInterrupt:
            cancelled = AnalysisCancelled("interrupted")
            for other in futures:
                other.cancel()

    _build_segments(manifest, config, results)
    manifest.analysis = AnalysisRun(
        files_analyzed=len(results),
        files_from_cache=sum(1 for result in results.values() if result.cached),
        files_failed=sum(1 for result in results.values() if result.error),
        completed=cancelled is None,
        hwaccel=hwaccel.method,
        # Run level warnings go on the manifest, not through the progress channel:
        # that channel is one event per file, and a front end may cancel from it.
        warnings=hwaccel_warnings,
    )
    if cancelled is not None:
        raise cancelled


def choose_hwaccel(config: AutocutConfig, pending: list[SourceFile]) -> tuple[Hwaccel, list[str]]:
    """Decide the run's decoder once, and prove it works before handing it to the pool.

    ``ffmpeg -hwaccels`` lists what was compiled in, not what the machine can
    actually run, so the choice is verified against the first file that has one.
    A failure demotes the whole run to software with a single warning rather than
    one per file.
    """
    hwaccel = select_hwaccel(config.analysis.hwaccel)
    warnings: list[str] = []
    if not hwaccel.enabled:
        return hwaccel, warnings

    probe_target = next(
        (
            source.proxy_path
            if source.proxy_path is not None and config.analysis.use_proxies
            else source.path
            for source in pending
            if source.path.exists()
        ),
        None,
    )
    if probe_target is None:
        return hwaccel, warnings

    works, why = verify_hwaccel(hwaccel, probe_target)
    if works:
        return hwaccel, warnings
    warnings.append(f"{hwaccel.label()} decoding unavailable, using software: {why}")
    return SOFTWARE, warnings


def _event(index: int, total: int, source: SourceFile, result: FileAnalysis) -> ProgressEvent:
    return ProgressEvent(
        stage="analyze",
        current=index,
        total=total,
        path=source.path,
        message="cached" if result.cached else "",
        extra={"cached": result.cached, "error": result.error},
    )


def _build_segments(
    manifest: Manifest, config: AutocutConfig, results: dict[str, FileAnalysis]
) -> None:
    """Turn per-file analysis into trimmed, ruled, scored and thumbnailed segments."""
    output_dir = Path(manifest.output_dir)
    segments: list[Segment] = []
    telemetry_by_file: dict[str, list[TelemetrySample]] = {}
    frames_by_segment: dict[str, np.ndarray] = {}
    sprites_by_segment: dict[str, np.ndarray] = {}

    for file_id, result in results.items():
        source = manifest.files.get(file_id)
        if source is None or result.entry is None:
            continue
        entry = result.entry
        telemetry_by_file[file_id] = [
            TelemetrySample.model_validate(sample) for sample in entry.telemetry
        ]
        timestamps = entry.arrays.get("timestamps", np.zeros(0))
        duration = source.duration_s
        # A takeoff is not a separate shot, so altitude crossings become boundaries
        # before trimming. See the split decision in the m1-analysis design.
        spans = split_on_altitude(
            entry.shot_bounds,
            [
                (sample.time_s, sample.height_m)
                for sample in telemetry_by_file[file_id]
                if sample.height_m is not None
            ],
            config.rules.drone.min_height_m,
            1.0 / config.analysis.sample_fps if config.analysis.sample_fps > 0 else 0.0,
        )
        trimmed = apply_trims(
            [span.bounds for span in spans], duration, source.source_class, config
        )

        pairs = zip(spans, trimmed, strict=True)
        for index, (span, bounds) in enumerate(pairs):
            start, stop = span.bounds
            segment_id = f"{file_id}:{index}"
            # The window metrics are measured over: the trimmed span when the trim
            # left anything, otherwise the raw span so the segment still gets numbers.
            window = bounds or (start, stop)
            indices = _frames_in(timestamps, window[0], window[1])
            if indices.size == 0 and timestamps.size:
                indices = np.array([int(np.argmin(np.abs(timestamps - window[0])))])
            segment = Segment(
                id=segment_id,
                file_id=file_id,
                start_s=start,
                end_s=stop,
                trimmed_start_s=bounds[0] if bounds else start,
                trimmed_end_s=bounds[1] if bounds else start,
                frame_count=int(indices.size),
                analyzed_from="proxy" if entry.source == "proxy" else "original",
                split_reason=span.split_reason,
                metrics=_aggregate(entry, indices, telemetry_by_file[file_id], window),
            )
            segments.append(segment)
            shot = shot_index(entry.shot_bounds, span.start_s)
            if entry.thumb_frames is not None and shot < entry.thumb_frames.shape[0]:
                frames_by_segment[segment_id] = entry.thumb_frames[shot]
            if shot < len(entry.sprites):
                sprites_by_segment[segment_id] = entry.sprites[shot]

    for segment in segments:
        assert segment.metrics is not None
        reason = apply_rules(
            segment, segment.metrics, telemetry_by_file.get(segment.file_id), config
        )
        if reason is not None:
            segment.outcome = "rejected"
            segment.reason = reason

    # Paired with the source class, because ranking happens within a class.
    scored = [
        (manifest.files[segment.file_id].source_class, segment.metrics)
        for segment in segments
        if segment.metrics is not None
    ]
    scores = score_metrics(scored, config.weights)
    for segment, score in zip(segments, scores, strict=True):
        segment.score = score

    quality = config.analysis.thumbnail_quality
    for segment in segments:
        frame = frames_by_segment.get(segment.id)
        if frame is not None and frame.size:
            segment.thumbnail = write_thumbnail(frame, segment.id, output_dir, quality)
        sprite = sprites_by_segment.get(segment.id)
        if sprite is not None and sprite.size:
            segment.sprite = write_sprite(sprite, segment.id, output_dir, quality)

    for segment in segments:
        manifest.segments[segment.id] = segment


def _aggregate(
    entry: CacheEntry,
    indices: np.ndarray,
    telemetry: list[TelemetrySample],
    span: tuple[float, float],
) -> Metrics:
    """Mean of every per-frame metric over the frames inside the segment."""

    def mean(name: str) -> float:
        values = entry.arrays.get(name)
        if values is None or values.size == 0 or indices.size == 0:
            return 0.0
        return float(values[indices].mean())

    # Half open, exactly like rules.segment_heights and the altitude split. A boundary
    # sample describes the span that starts there; counting it on both sides would make
    # a cruise segment report the takeoff height it was split away from.
    heights = [
        sample.height_m
        for sample in telemetry
        if sample.height_m is not None and span[0] <= sample.time_s < span[1]
    ]
    speeds = [
        sample.speed_h_ms
        for sample in telemetry
        if sample.speed_h_ms is not None and span[0] <= sample.time_s < span[1]
    ]
    return Metrics(
        sharpness=mean("sharpness"),
        exposure_clipped=mean("clipping"),
        motion=mean("motion"),
        stability=mean("stability"),
        colorfulness=mean("colorfulness"),
        min_height_m=min(heights) if heights else None,
        mean_speed_ms=sum(speeds) / len(speeds) if speeds else None,
    )

"""Write the `_selects/` folder: cut, normalize and number the selected clips.

This is the stage the whole project exists for. Everything before it produces
numbers in a manifest; this produces the folder that gets dragged into CapCut.

Export is resumable because re-encoding 40 clips is the only slow thing left once
the analysis cache is warm. Each clip records a fingerprint of everything its
output depends on, and a clip whose file is still on disk with a matching
fingerprint is skipped. An output that no longer belongs to any current clip is
moved to `_selects/_stale/` rather than deleted: a mistaken `select` run should
cost a re-encode, never the previous edit.

Clips run in a process pool half the size of the core count, because libx264 is
already threaded and oversubscribing it makes the whole export slower.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import shutil
import subprocess
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.ffmpeg_cmd import (
    ExportOverrides,
    ExportPlan,
    build_export_command,
    plan_export,
    resolve_frame,
    resolve_target_fps,
)
from autocut.core.ingest import physical_cores
from autocut.core.manifest import ExportRun, Manifest, Segment, SourceFile
from autocut.core.naming import (
    REJECTS_DIR,
    SELECTS_DIR,
    STALE_DIR,
    clip_name,
    stale_outputs,
)
from autocut.core.select import absolute_time

FFMPEG_TIMEOUT_S = 1800.0


@dataclass(slots=True)
class ClipResult:
    """What happened to one clip."""

    segment_id: str
    output: Path
    fingerprint: str
    skipped: bool = False
    error: str | None = None


@dataclass(slots=True)
class ExportResult:
    """What one export pass did."""

    target_fps: float = 0.0
    exported: int = 0
    skipped: int = 0
    failed: int = 0
    slow_motion: int = 0
    fps_converted: int = 0
    stale_moved: int = 0
    frame: tuple[int, int] = (0, 0)
    """The common frame this run put every clip on, or ``(0, 0)`` when it did not."""

    selects_dir: Path | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.exported + self.skipped + self.failed


def fingerprint(plan: ExportPlan, source_id: str) -> str:
    """A digest of everything that would change the bytes of this output.

    ``source_id`` is the cache key from ADR 6, so it already covers the source path,
    its size, its mtime and a hash of its ends. Everything else in the digest is a
    decision this run made, which is what makes a settings change re-encode and a
    re-run with the same settings skip.
    """
    payload = {
        "source": source_id,
        "start": round(plan.source_start_s, 4),
        "source_duration": round(plan.source_duration_s, 4),
        "out_duration": round(plan.out_duration_s, 4),
        "fps": round(plan.target_fps, 4),
        "mode": plan.mode,
        "codec": plan.codec,
        "crf": plan.crf,
        "pix_fmt": plan.pix_fmt,
        "audio": plan.audio,
        "scale": [plan.scale_w, plan.scale_h],
        "slow": plan.slow_motion_ratio,
        "vertical": plan.vertical_strategy if plan.is_vertical else None,
        "pad": [plan.pad_w, plan.pad_h],
        "crop": [plan.crop_w, plan.crop_h],
        "lut": str(plan.lut) if plan.lut else None,
        "lens": plan.lens_correction,
    }
    if plan.frame_w and plan.frame_h:
        # Added only when the clip is padded onto a frame, so a project exported
        # before the common frame existed keeps its digests and its files.
        payload["frame"] = [plan.frame_w, plan.frame_h]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()[:16]


def export_one(plan: ExportPlan, segment_id: str, digest: str) -> ClipResult:
    """Run ffmpeg for one clip. Runs inside a pool worker."""
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    command = build_export_command(plan)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return ClipResult(segment_id, plan.output, digest, error="ffmpeg not found on PATH")
    except subprocess.SubprocessError as exc:
        return ClipResult(segment_id, plan.output, digest, error=str(exc))

    if completed.returncode != 0 or not plan.output.exists():
        error = _first_line(completed.stderr) or f"ffmpeg exit status {completed.returncode}"
        # A partial file would be picked up as a finished output by the next run.
        plan.output.unlink(missing_ok=True)
        return ClipResult(segment_id, plan.output, digest, error=error)
    return ClipResult(segment_id, plan.output, digest)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


@dataclass(slots=True)
class _Job:
    """One clip to consider, before it is known whether it has to be encoded."""

    segment: Segment
    plan: ExportPlan
    digest: str


def _selected(manifest: Manifest) -> list[Segment]:
    """Selected segments in edit order, falling back to chronology for a missing order."""
    chosen = [s for s in manifest.segments.values() if s.outcome == "selected"]
    return sorted(chosen, key=lambda s: (s.order if s.order is not None else 0, s.id))


def _rejected(manifest: Manifest) -> list[Segment]:
    """Rejected segments in capture order, which is the only order they have."""
    rejected = [s for s in manifest.segments.values() if s.outcome == "rejected"]

    def when(segment: Segment) -> tuple[datetime, str]:
        moment = absolute_time(manifest.files.get(segment.file_id), segment)
        return moment or datetime.fromtimestamp(0, tz=UTC), segment.id

    return sorted(rejected, key=when)


def _build_jobs(
    manifest: Manifest,
    config: AutocutConfig,
    overrides: ExportOverrides,
    out_dir: Path,
) -> tuple[list[_Job], list[str]]:
    """One job per clip that should exist after this run, plus any skipped-file notes."""
    jobs: list[_Job] = []
    warnings: list[str] = []
    selects = out_dir / SELECTS_DIR

    for order, segment in enumerate(_selected(manifest), start=1):
        source = manifest.files.get(segment.file_id)
        if source is None:
            warnings.append(f"{segment.id} has no source file in the manifest, skipped")
            continue
        jobs.append(_job(segment, source, manifest, config, overrides, selects, order, None))

    if overrides.rejects or config.export.keep_rejects:
        rejects = out_dir / REJECTS_DIR
        for order, segment in enumerate(_rejected(manifest), start=1):
            source = manifest.files.get(segment.file_id)
            if source is None:
                continue
            jobs.append(
                # The reason takes the place of the tag: a rejects folder is only ever
                # read to ask why something is in it.
                _job(
                    segment,
                    source,
                    manifest,
                    config,
                    overrides,
                    rejects,
                    order,
                    segment.reason or "rejected",
                )
            )
    return jobs, warnings


def _job(
    segment: Segment,
    source: SourceFile,
    manifest: Manifest,
    config: AutocutConfig,
    overrides: ExportOverrides,
    directory: Path,
    order: int,
    tag: str | None,
) -> _Job:
    plan = plan_export(segment, source, manifest, config, overrides)
    name = clip_name(segment, source, order, plan.out_duration_s, tag)
    plan = _with_output(plan, directory / name)
    return _Job(segment=segment, plan=plan, digest=fingerprint(plan, source.id))


def _with_output(plan: ExportPlan, output: Path) -> ExportPlan:
    """``ExportPlan`` is frozen, so naming the output means replacing it."""
    return replace(plan, output=output)


def _move_stale(out_dir: Path, expected: set[str]) -> tuple[int, list[str]]:
    """Move outputs that no longer belong to a current clip out of the way."""
    selects = out_dir / SELECTS_DIR
    stale = stale_outputs(selects, expected)
    if not stale:
        return 0, []
    target = selects / STALE_DIR
    target.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    moved = 0
    for path in stale:
        try:
            shutil.move(str(path), str(target / path.name))
            moved += 1
        except OSError as exc:
            warnings.append(f"could not move {path.name} to {STALE_DIR}: {exc}")
    return moved, warnings


def export_clips(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
    overrides: ExportOverrides | None = None,
) -> ExportResult:
    """Cut every selected clip into `_selects/` and record what happened."""
    overrides = overrides or ExportOverrides()
    out_dir = Path(manifest.output_dir)
    target_fps = resolve_target_fps(manifest, config, overrides)
    # Recorded before the clips run so every plan in this pass agrees on the target,
    # and so a later pass reuses it instead of re-deriving it from a changed selection.
    manifest.export.target_fps = target_fps

    frame = resolve_frame(manifest, config, overrides)
    result = ExportResult(target_fps=target_fps, selects_dir=out_dir / SELECTS_DIR, frame=frame)
    jobs, warnings = _build_jobs(manifest, config, overrides, out_dir)
    result.warnings.extend(warnings)

    moved, move_warnings = _move_stale(
        out_dir,
        {job.plan.output.name for job in jobs if job.plan.output.parent.name == SELECTS_DIR},
    )
    result.stale_moved = moved
    result.warnings.extend(move_warnings)

    for job in jobs:
        job.segment.export_mode = job.plan.mode
        job.segment.fps_converted = job.plan.fps_converted
        job.segment.export_error = None
        if job.plan.slow_motion:
            result.slow_motion += 1
        if job.plan.fps_converted:
            result.fps_converted += 1

    pending: list[_Job] = []
    for job in jobs:
        if _up_to_date(job):
            result.skipped += 1
        else:
            pending.append(job)

    _run(pending, config, progress, result, len(jobs))
    _record_run(manifest, config, overrides, result)
    return result


def export_is_current(
    manifest: Manifest,
    config: AutocutConfig,
    overrides: ExportOverrides | None = None,
) -> bool:
    """Whether every selected clip on disk was written from exactly these settings.

    The same jobs and the same test the export itself uses, so a caller that needs an
    export before it can do its own work asks one question rather than re-deriving the
    plan and getting a subtly different answer.
    """
    jobs, _warnings = _build_jobs(
        manifest, config, overrides or ExportOverrides(), Path(manifest.output_dir)
    )
    selects = [job for job in jobs if job.plan.output.parent.name == SELECTS_DIR]
    return bool(selects) and all(_up_to_date(job) for job in selects)


def _up_to_date(job: _Job) -> bool:
    """Whether the output on disk was made from exactly these settings, for this clip.

    The last test is not redundant. The digest covers what the bytes look like and not
    what the file is called, and the name carries the clip's position in the edit, so a
    re-ordered selection can hand a clip the file its neighbour wrote: same day, same
    class, same tag, same length, same index, different footage. Requiring the recorded
    output to be the one this plan writes makes a re-order re-encode the clips whose
    position moved, which is the only way the folder can be trusted.
    """
    return (
        job.plan.output.exists()
        and job.segment.export_fingerprint == job.digest
        and job.segment.exported_path is not None
        and Path(job.segment.exported_path) == job.plan.output
    )


def _run(
    pending: list[_Job],
    config: AutocutConfig,
    progress: ProgressCallback,
    result: ExportResult,
    total: int,
) -> None:
    """Encode the clips that need it, in parallel unless there is only one."""
    if not pending:
        progress(ProgressEvent(stage="export", current=total, total=total, message="all skipped"))
        return

    done = result.skipped
    workers = max(1, (config.analysis.workers or physical_cores()) // 2)
    if workers == 1 or len(pending) == 1:
        for job in pending:
            done += 1
            try:
                clip = export_one(job.plan, job.segment.id, job.digest)
            except Exception as exc:  # noqa: BLE001 - becomes this clip's error, see decision 2
                clip = ClipResult(
                    job.segment.id, job.plan.output, job.digest, error=f"worker failed: {exc}"
                )
            _finish(job, clip, result, progress, done, total)
        return

    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=min(workers, len(pending)), mp_context=context) as pool:
        futures: dict[Future[ClipResult], _Job] = {
            pool.submit(export_one, job.plan, job.segment.id, job.digest): job for job in pending
        }
        for future in as_completed(futures):
            job = futures[future]
            done += 1
            try:
                clip = future.result()
            except Exception as exc:  # noqa: BLE001 - see decision 2
                clip = ClipResult(
                    job.segment.id, job.plan.output, job.digest, error=f"worker failed: {exc}"
                )
            _finish(job, clip, result, progress, done, total)


def _finish(
    job: _Job,
    clip: ClipResult,
    result: ExportResult,
    progress: ProgressCallback,
    done: int,
    total: int,
) -> None:
    """Record one clip's outcome. A failure is recorded and never stops the others."""
    _record(job.segment, clip.output, clip.fingerprint, clip.error)
    if clip.error is None:
        result.exported += 1
    else:
        result.failed += 1
        result.errors.append((job.segment.id, clip.error))
    progress(
        ProgressEvent(
            stage="export",
            current=done,
            total=total,
            path=clip.output,
            message=clip.error or "",
            extra={"failed": clip.error is not None},
        )
    )


def _record(segment: Segment, output: Path, digest: str, error: str | None) -> None:
    if error is not None:
        segment.export_error = error
        segment.exported_path = None
        segment.export_fingerprint = None
        return
    segment.exported_path = output
    segment.export_fingerprint = digest
    segment.export_error = None


def _record_run(
    manifest: Manifest,
    config: AutocutConfig,
    overrides: ExportOverrides,
    result: ExportResult,
) -> None:
    manifest.export = ExportRun(
        ran_at=datetime.now(UTC),
        target_fps=result.target_fps,
        max_width=config.export.max_width,
        max_height=config.export.max_height,
        mode="fast" if overrides.fast else config.export.mode,
        codec=config.export.codec,
        exported=result.exported,
        skipped=result.skipped,
        failed=result.failed,
        slow_motion=result.slow_motion,
        fps_converted=result.fps_converted,
        stale_moved=result.stale_moved,
        # Kept from the previous run when this one did not use a frame, so turning the
        # frame off for one export does not let it grow on the next.
        frame_width=result.frame[0] or manifest.export.frame_width,
        frame_height=result.frame[1] or manifest.export.frame_height,
        warnings=result.warnings,
    )

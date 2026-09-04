"""The one object that owns a project.

Every screen reads from here and writes through here, and nothing else writes
``manifest.json``. That is the whole point of ADR 9: two hard problems, keeping the
screens consistent with each other and keeping long work off the UI thread, are
solved once in this class instead of once per screen.

The state calls the core the way the CLI does, with the same functions in the same
order, so a project built in the window and a project built from the command line are
the same project. What the state adds is a Qt signal after every mutation and a
debounced save, so a crash costs at most one debounce interval of review work.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from autocut.core.analyze import analyze_files
from autocut.core.config import AutocutConfig
from autocut.core.describe import DescribeResult, describe_project
from autocut.core.embeddings import EmbedResult, embed_project
from autocut.core.events import ProgressCallback, ProgressEvent
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest
from autocut.core.providers import cloud_enabled, find_key
from autocut.core.providers.openrouter import OpenRouterProvider
from autocut.core.select import SelectionOverrides, select_clips
from autocut.core.tags import TagResult, tag_project
from autocut.gui.workers import CancelFlag, CoreWorker

MANIFEST_NAME = "manifest.json"
CONFIG_NAME = "autocut.toml"

#: Long enough that dragging a slider is one save and not fifty, short enough that a
#: crash costs a moment of review rather than a session of it.
AUTOSAVE_DEBOUNCE_MS = 1500


@dataclass(slots=True)
class AnalysisOutcome:
    """What one full analysis run did, for the screen to summarize."""

    files: int = 0
    unreadable: int = 0
    segments: int = 0
    cached_files: int = 0
    embed: EmbedResult | None = None
    tag: TagResult | None = None
    describe: DescribeResult | None = None


class ProjectState(QObject):
    """Manifest, configuration and the single worker slot, with signals for both."""

    segments_changed = Signal(list)
    """Ids of the segments that changed, empty when every one of them did."""

    selection_changed = Signal()
    project_changed = Signal()
    """A different project is open now, so a screen showing which one has to catch up."""

    progress = Signal(object)
    stage_started = Signal(str)
    stage_finished = Signal(str)
    stage_cancelled = Signal(str)
    error = Signal(str)
    saved = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.manifest: Manifest | None = None
        self.config = AutocutConfig()
        self.output_dir: Path | None = None
        self._worker: CoreWorker | None = None
        self._flag = CancelFlag()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_now)

    # --- the project itself -------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.manifest is not None and self.output_dir is not None

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @property
    def manifest_path(self) -> Path | None:
        return self.output_dir / MANIFEST_NAME if self.output_dir is not None else None

    @property
    def config_path(self) -> Path | None:
        return self.output_dir / CONFIG_NAME if self.output_dir is not None else None

    def new_project(self, sources: Sequence[Path], out: Path) -> None:
        """Start a project in ``out``, or adopt the one already there.

        Reopening a folder that holds a manifest keeps the analysis in it, because a
        user who picks their own output folder again means to continue, not to throw
        away an hour of probing.
        """
        out.mkdir(parents=True, exist_ok=True)
        path = out / MANIFEST_NAME
        resolved = [Path(source).resolve() for source in sources]
        self.config = AutocutConfig.load(out / CONFIG_NAME)
        if path.exists():
            manifest = Manifest.load(path)
            manifest.sources = resolved or manifest.sources
            manifest.output_dir = out
        else:
            now = datetime.now(UTC)
            manifest = Manifest(created_at=now, updated_at=now, sources=resolved, output_dir=out)
        manifest.config_snapshot = self.config.model_dump(mode="json")
        self.manifest = manifest
        self.output_dir = out
        self.project_changed.emit()
        self.segments_changed.emit([])
        self.selection_changed.emit()

    def open_project(self, out: Path) -> None:
        """Open the project in ``out``. Raises ``FileNotFoundError`` without a manifest."""
        path = out / MANIFEST_NAME
        if not path.exists():
            raise FileNotFoundError(f"No {MANIFEST_NAME} in {out}")
        self.manifest = Manifest.load(path)
        self.output_dir = out
        self.manifest.output_dir = out
        self.config = AutocutConfig.load(out / CONFIG_NAME)
        self.project_changed.emit()
        self.segments_changed.emit([])
        self.selection_changed.emit()

    def refresh_config_snapshot(self) -> None:
        """Copy the current configuration onto the manifest and save.

        Called after a profile or the settings dialog changes the config, so the
        manifest records the settings the project was built with rather than the ones
        it happened to be created with.
        """
        if self.manifest is None:
            return
        self.manifest.config_snapshot = self.config.model_dump(mode="json")
        self.schedule_save()

    def close_project(self) -> None:
        """Save and forget. Called when the window closes or another project opens."""
        self.save_now()
        self.manifest = None
        self.output_dir = None

    # --- saving -------------------------------------------------------------

    def touch(self, changed: Sequence[str] = ()) -> None:
        """Record a mutation: tell the screens, and start the save clock."""
        self.segments_changed.emit(list(changed))
        self.schedule_save()

    def schedule_save(self) -> None:
        """Save soon. Restarting the timer is what makes it a debounce."""
        if self.is_open:
            self._save_timer.start()

    def save_now(self) -> None:
        """Write the manifest immediately and stop any pending save."""
        self._save_timer.stop()
        manifest = self.manifest
        path = self.manifest_path
        if manifest is None or path is None:
            return
        manifest.updated_at = datetime.now(UTC)
        manifest.save(path)
        self.saved.emit()

    # --- running core stages ------------------------------------------------

    def run_stage(self, name: str, work: Callable[[ProgressCallback], Any]) -> bool:
        """Run ``work`` on the worker thread. False when one is already running.

        Refused rather than queued: two stages over one manifest would race, and a user
        who presses a second button wants to know it did nothing, not to have it happen
        later for reasons they have forgotten by then.
        """
        if self.is_running:
            self.error.emit(f"{self._worker.name if self._worker else 'A stage'} is still running")
            return False
        self._flag.clear()
        worker = CoreWorker(name, work, self._flag, self)
        worker.progressed.connect(self.progress.emit)
        worker.done.connect(lambda result: self._stage_done(name, result))
        worker.cancelled.connect(lambda: self._stage_cancelled(name))
        worker.failed.connect(self._stage_failed)
        worker.finished.connect(self._clear_worker)
        self._worker = worker
        self.stage_started.emit(name)
        worker.start()
        return True

    def cancel(self) -> None:
        """Ask the running stage to stop at its next progress report."""
        self._flag.cancel()

    def wait_for_stage(self, timeout_ms: int = 60_000) -> bool:
        """Block until the worker is done. For tests and for closing the window."""
        worker = self._worker
        if worker is None:
            return True
        return bool(worker.wait(timeout_ms))

    def _stage_done(self, name: str, result: object) -> None:
        self.segments_changed.emit([])
        self.selection_changed.emit()
        self.save_now()
        self.stage_finished.emit(name)
        self._last_result = result

    def _stage_cancelled(self, name: str) -> None:
        # Whatever the stage did reach is worth keeping: analysis is per file and the
        # cache makes the rest of it cheap to resume.
        self.segments_changed.emit([])
        self.save_now()
        self.stage_cancelled.emit(name)

    def _stage_failed(self, message: str) -> None:
        self.error.emit(message)
        worker = self._worker
        if worker is not None and worker.traceback_text and self.output_dir is not None:
            log = self.output_dir / "gui-errors.log"
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            with log.open("a", encoding="utf-8") as fh:
                fh.write(f"--- {stamp} {message}\n{worker.traceback_text}\n")

    def _clear_worker(self) -> None:
        self._worker = None

    @property
    def last_result(self) -> object:
        return getattr(self, "_last_result", None)

    # --- the stages themselves ---------------------------------------------

    def run_analysis(self) -> bool:
        """Scan, probe, analyze, embed, tag and describe, as ``autocut analyze`` does.

        One worker run rather than five, because the user asked for an analyzed project
        and the stages have no decision between them. The stage names in the progress
        events are what the screen turns into steps.
        """
        manifest = self.manifest
        if manifest is None:
            return False
        config = self.config

        def work(progress: ProgressCallback) -> AnalysisOutcome:
            outcome = AnalysisOutcome()
            files = ingest(list(manifest.sources), config, progress)
            manifest.files = {source.id: source for source in files}
            outcome.files = len(files)
            outcome.unreadable = sum(1 for source in files if source.error)

            cached = 0

            def on_analysis(event: ProgressEvent) -> None:
                nonlocal cached
                if event.extra.get("cached"):
                    cached += 1
                progress(event)

            analyze_files(manifest, config, on_analysis)
            outcome.cached_files = cached
            outcome.segments = len(manifest.segments)
            outcome.embed = embed_project(manifest, config, progress)
            manifest.analysis.embedding_model = outcome.embed.model
            manifest.analysis.embedding_device = outcome.embed.device
            outcome.tag = tag_project(manifest, config)
            outcome.describe = self._describe(manifest, config, progress)
            return outcome

        return self.run_stage("analysis", work)

    def _describe(
        self, manifest: Manifest, config: AutocutConfig, progress: ProgressCallback
    ) -> DescribeResult:
        """The cloud pass, or the reason there was none. Never raises for a missing key."""
        enabled, reason = cloud_enabled(config)
        if not enabled:
            return DescribeResult(scope=config.providers.describe_scope, skipped_reason=reason)
        key = find_key()
        assert key is not None  # cloud_enabled already established there is one
        with OpenRouterProvider(key, config) as provider:
            return describe_project(manifest, config, provider, progress)

    def run_selection(self, overrides: SelectionOverrides | None = None) -> bool:
        """Re-score and re-select. Fast enough to run on the UI thread.

        Selection reads the metrics already in the manifest and touches no file, so it
        is the one stage that does not need a worker. That is what makes the live
        slider of SPEC.md section 11 possible: move it, re-select, emit one signal.
        """
        manifest = self.manifest
        if manifest is None or self.is_running:
            return False
        select_clips(manifest, self.config, overrides)
        self.selection_changed.emit()
        self.segments_changed.emit([])
        self.schedule_save()
        return True

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

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QUndoCommand, QUndoStack

from autocut.core.analyze import analyze_files
from autocut.core.config import AutocutConfig
from autocut.core.describe import DescribeResult, describe_project
from autocut.core.embeddings import EmbedResult, embed_project
from autocut.core.events import ProgressCallback, ProgressEvent
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest, Segment, UserDecision
from autocut.core.montage import MontageResult, build_montage, is_current
from autocut.core.providers import cloud_enabled, find_key
from autocut.core.providers.openrouter import OpenRouterProvider
from autocut.core.score import rescore
from autocut.core.select import SelectionOverrides, SelectionResult, select_clips
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


class DecisionCommand(QUndoCommand):
    """One keep, reject or clear, undoable.

    The command carries the previous decision rather than a way to recompute it,
    because there is nothing to recompute: a decision is what a person said, and undo
    means saying the previous thing again. Redo and undo both re-select, since the
    edit is what the decision was about.
    """

    def __init__(self, state: ProjectState, segment_id: str, decision: UserDecision | None) -> None:
        super().__init__(_decision_text(decision, segment_id))
        self._state = state
        self._segment_id = segment_id
        self._after = decision
        segment = state.segment(segment_id)
        self._before = segment.user_decision if segment is not None else None

    def redo(self) -> None:
        self._state.apply_decision(self._segment_id, self._after)

    def undo(self) -> None:
        self._state.apply_decision(self._segment_id, self._before)


class BoundsCommand(QUndoCommand):
    """Hand set in and out points, undoable as one step."""

    def __init__(
        self, state: ProjectState, segment_id: str, bounds: tuple[float, float] | None
    ) -> None:
        super().__init__(f"trim {segment_id}" if bounds else f"clear trim on {segment_id}")
        self._state = state
        self._segment_id = segment_id
        self._after = bounds
        segment = state.segment(segment_id)
        self._before = segment.user_bounds if segment is not None else None

    def redo(self) -> None:
        self._state.apply_bounds(self._segment_id, self._after)

    def undo(self) -> None:
        self._state.apply_bounds(self._segment_id, self._before)


class SwapCommand(QUndoCommand):
    """Keep one clip of a group and reject the current pick, in one undo step.

    Two decisions rather than one, because that is what swapping a duplicate means,
    and a user who regrets it wants both back at once.
    """

    def __init__(self, state: ProjectState, keep_id: str, reject_id: str) -> None:
        super().__init__(f"swap {reject_id} for {keep_id}")
        self._state = state
        self._keep_id = keep_id
        self._reject_id = reject_id
        keep = state.segment(keep_id)
        reject = state.segment(reject_id)
        self._before = (
            keep.user_decision if keep is not None else None,
            reject.user_decision if reject is not None else None,
        )

    def redo(self) -> None:
        self._state.apply_decision(self._keep_id, "keep", reselect=False)
        self._state.apply_decision(self._reject_id, "reject")

    def undo(self) -> None:
        self._state.apply_decision(self._keep_id, self._before[0], reselect=False)
        self._state.apply_decision(self._reject_id, self._before[1])


def _decision_text(decision: UserDecision | None, segment_id: str) -> str:
    if decision is None:
        return f"clear the decision on {segment_id}"
    return f"{decision} {segment_id}"


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
    stage_ended = Signal(str)
    """The worker of the named stage has stopped, however it stopped.

    Emitted after ``is_running`` has turned false, so a slot may start the next stage
    or close the window. ``stage_finished`` is too early for either: it arrives while
    the thread that returned the result may still be winding down.
    """

    error = Signal(str)
    saved = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.manifest: Manifest | None = None
        self.config = AutocutConfig()
        self.output_dir: Path | None = None
        #: Whether the Review right panel is showing. Session state, not project state:
        #: it is about the width of the window in front of the user, so it survives
        #: opening another project and is never written to the manifest. None until the
        #: window has decided from its own width.
        self.review_panel_visible: bool | None = None
        self._worker: CoreWorker | None = None
        self._flag = CancelFlag()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_now)
        self.undo_stack = QUndoStack(self)
        self._reselect_timer = QTimer(self)
        self._reselect_timer.setSingleShot(True)
        self._reselect_timer.setInterval(self.config.gui.slider_debounce_ms)
        self._reselect_timer.timeout.connect(self._run_pending_reselect)
        self._pending_rescore = False
        self.last_selection: SelectionResult | None = None

    # --- the project itself -------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.manifest is not None and self.output_dir is not None

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @property
    def running_stage(self) -> str | None:
        """The name of the stage on the worker, or None when nothing runs."""
        return self._worker.name if self.is_running and self._worker is not None else None

    @property
    def cancel_requested(self) -> bool:
        """Whether the current or last stage was asked to stop."""
        return self._flag.cancelled

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

    def close_project(self) -> bool:
        """Stop any stage, save, and forget. False, with nothing saved, if it would not stop.

        The stage is cancelled and waited for rather than abandoned, because the save
        that follows reads the manifest and the worker is still writing it. The wait is
        short (``gui.close_wait_ms``): the cancel is only seen between files, so a stage
        in the middle of an encode can outlast any sensible wait, and saving then would
        serialise a manifest the worker is still writing. The project stays open instead,
        and the window closes itself once the stage has ended.
        """
        if self.is_running:
            self.cancel()
            if not self.wait_for_stage(self.config.gui.close_wait_ms):
                return False
        self.save_now(force=True)
        self.manifest = None
        self.output_dir = None
        return True

    # --- saving -------------------------------------------------------------

    def touch(self, changed: Sequence[str] = ()) -> None:
        """Record a mutation: tell the screens, and start the save clock."""
        self.segments_changed.emit(list(changed))
        self.schedule_save()

    def schedule_save(self) -> None:
        """Save soon. Restarting the timer is what makes it a debounce.

        Nothing is scheduled during a stage: the worker is mutating the manifest and a
        save is a full read of it.
        """
        if self.is_open and not self.is_running:
            self._save_timer.start()

    def save_now(self, force: bool = False) -> bool:
        """Write the manifest immediately and stop any pending save.

        Refused while a stage runs, because serialising the manifest reads every
        segment while the worker is still writing them, and a timer armed before the
        run would otherwise fire straight into that. ``force`` is for the two callers
        that know the writing has stopped: the stage's own completion handlers, which
        run on the UI thread after the work returned, and ``close_project``, which
        cancels and waits first.
        """
        self._save_timer.stop()
        if self.is_running and not force:
            return False
        manifest = self.manifest
        path = self.manifest_path
        if manifest is None or path is None:
            return False
        manifest.updated_at = datetime.now(UTC)
        manifest.save(path)
        self.saved.emit()
        return True

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
        # A save armed before this call would fire into the running worker, which is
        # writing the manifest a save has to read.
        self._save_timer.stop()
        self._flag.clear()
        worker = CoreWorker(name, work, self._flag, self)
        worker.progressed.connect(self.progress.emit)
        worker.done.connect(lambda result: self._stage_done(name, result))
        worker.cancelled.connect(lambda: self._stage_cancelled(name))
        worker.failed.connect(self._stage_failed)
        worker.finished.connect(self._clear_worker)
        self._worker = worker
        # Load bearing order: the signal goes out before the thread starts, so every
        # screen has disabled its controls by the time anything can touch the manifest.
        # Starting first would leave a window in which the UI still believes it is idle.
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
        # Forced: this runs on the UI thread after the stage's callable returned, so
        # the manifest is no longer being written even though the thread may still be
        # winding down. One save per stage, here, rather than a debounced one.
        # Recorded before the signal, not after: a screen reading ``last_result`` in
        # its ``stage_finished`` handler is the normal case, and setting it afterwards
        # handed every one of them the previous run's result.
        self._last_result = result
        self.segments_changed.emit([])
        self.selection_changed.emit()
        self.save_now(force=True)
        self.stage_finished.emit(name)

    def _stage_cancelled(self, name: str) -> None:
        # Whatever the stage did reach is worth keeping: analysis is per file and the
        # cache makes the rest of it cheap to resume. Forced for the same reason as in
        # _stage_done: the callable has returned by the time this slot runs.
        self.segments_changed.emit([])
        self.save_now(force=True)
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
        # The worker that finished, not whichever one is current when this slot runs: a
        # completion handler may already have started the next stage by then.
        worker = self.sender()
        if not isinstance(worker, CoreWorker):
            return
        # Cleared before the signal, so a slot that closes the window or starts another
        # stage finds nothing running. Deleted after it, so the thread object does not
        # stay parented to the state for the rest of the session.
        if self._worker is worker:
            self._worker = None
        # ``finished`` is emitted from inside the thread, before it has exited. Joined
        # here, where the wait releases the GIL and lasts only the thread's own wind
        # down: otherwise the deferred delete can run inside a native call that holds
        # the GIL, and ~QThread then waits for a thread that needs the GIL to exit.
        worker.wait()
        self.stage_ended.emit(worker.name)
        worker.deleteLater()

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

    # --- review decisions ---------------------------------------------------

    def segment(self, segment_id: str) -> Segment | None:
        manifest = self.manifest
        return manifest.segments.get(segment_id) if manifest is not None else None

    def set_decision(self, segment_id: str, decision: UserDecision | None) -> bool:
        """Keep, reject or clear, through the undo stack. False while a stage runs."""
        if self.manifest is None or self.is_running:
            return False
        self.undo_stack.push(DecisionCommand(self, segment_id, decision))
        return True

    def toggle_keep(self, segment_id: str) -> bool:
        """Space on a card: keep it, or clear the keep it already has."""
        segment = self.segment(segment_id)
        if segment is None:
            return False
        return self.set_decision(segment_id, None if segment.kept else "keep")

    def set_user_bounds(self, segment_id: str, bounds: tuple[float, float] | None) -> bool:
        if self.manifest is None or self.is_running:
            return False
        self.undo_stack.push(BoundsCommand(self, segment_id, bounds))
        return True

    def swap_pick(self, keep_id: str, reject_id: str) -> bool:
        """Take the other clip of a group: one undo step, one re-selection."""
        if self.manifest is None or self.is_running:
            return False
        self.undo_stack.push(SwapCommand(self, keep_id, reject_id))
        return True

    def apply_decision(
        self, segment_id: str, decision: UserDecision | None, reselect: bool = True
    ) -> None:
        """Write the decision and re-select. Called by the undo commands, not directly."""
        segment = self.segment(segment_id)
        if segment is None:
            return
        segment.user_decision = decision
        self.segments_changed.emit([segment_id])
        if reselect:
            self.request_reselect(immediate=True)

    def apply_bounds(self, segment_id: str, bounds: tuple[float, float] | None) -> None:
        segment = self.segment(segment_id)
        if segment is None:
            return
        if bounds is None:
            segment.user_start_s = segment.user_end_s = None
        else:
            segment.user_start_s, segment.user_end_s = bounds
        self.segments_changed.emit([segment_id])
        self.request_reselect(immediate=True)

    # --- re-scoring and re-selecting ---------------------------------------

    def request_reselect(self, rescore_first: bool = False, immediate: bool = False) -> None:
        """Redo the edit, coalescing a burst of slider moves into one run.

        A drag emits a value per pixel and each one would otherwise be a selection, so
        the timer is the whole point. A decision is a single deliberate act and asks for
        ``immediate``: waiting a quarter of a second to see a rejected clip leave the
        grid feels like a bug.
        """
        self._pending_rescore = self._pending_rescore or rescore_first
        if self.is_running:
            return
        self._reselect_timer.setInterval(self.config.gui.slider_debounce_ms)
        if immediate:
            self._reselect_timer.stop()
            self._run_pending_reselect()
            return
        self._reselect_timer.start()

    def _run_pending_reselect(self) -> None:
        rescore_first = self._pending_rescore
        self._pending_rescore = False
        self.run_selection(rescore_first=rescore_first)

    def candidate_count(self) -> int:
        manifest = self.manifest
        if manifest is None:
            return 0
        return sum(1 for segment in manifest.segments.values() if segment.outcome != "rejected")

    def reselect_needs_worker(self) -> bool:
        """Whether this project is big enough to hand selection to the thread.

        Measured rather than assumed, which is why it is a threshold and not a rule:
        selection reads cached arrays only and takes well under a second on a normal
        folder, so threading every re-selection would buy nothing and cost the
        simplicity of a synchronous slider.
        """
        threshold = self.config.gui.reselect_worker_threshold
        return threshold > 0 and self.candidate_count() > threshold

    def run_montage(self, track: Path | None = None, force: bool = False) -> bool:
        """Render the montage preview on the worker. False when one is already running.

        Through the worker because it is ffmpeg over every selected clip, which is the
        one thing on this screen that takes real time. The fingerprint check happens
        inside, so pressing Play all on an untouched edit returns a result without
        rendering and the worker finishes immediately.
        """
        manifest = self.manifest
        config = self.config
        if manifest is None or self.is_running:
            return False

        def work(progress: ProgressCallback) -> MontageResult:
            return build_montage(manifest, config, progress, track=track, force=force)

        return self.run_stage("montage", work)

    def montage_is_current(self, track: Path | None = None) -> bool:
        """Whether the montage on disk still describes this edit."""
        manifest = self.manifest
        if manifest is None:
            return False
        return bool(is_current(manifest, self.config, track))

    def run_selection(
        self,
        overrides: SelectionOverrides | None = None,
        rescore_first: bool = False,
    ) -> bool:
        """Re-score and re-select, inline or on the worker depending on the size.

        Selection reads the metrics already in the manifest and touches no file, so on
        a normal project it is the one stage that needs no worker, and that is what
        makes the live slider of SPEC.md section 11 possible: move it, re-select, emit
        one signal. A project past ``gui.reselect_worker_threshold`` candidates goes
        through the thread instead, because a slider that freezes the window is worse
        than a slider that answers a moment later.
        """
        manifest = self.manifest
        config = self.config
        if manifest is None or self.is_running:
            return False

        if self.reselect_needs_worker():

            def work(_progress: ProgressCallback) -> SelectionResult:
                if rescore_first:
                    rescore(manifest, config.weights)
                return select_clips(manifest, config, overrides)

            return self.run_stage("selection", work)

        cursor = Qt.CursorShape.BusyCursor
        QGuiApplication.setOverrideCursor(cursor)
        try:
            if rescore_first:
                rescore(manifest, config.weights)
            self.last_selection = select_clips(manifest, config, overrides)
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.selection_changed.emit()
        self.segments_changed.emit([])
        self.schedule_save()
        return True

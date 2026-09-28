"""Screen 2: running the pipeline, and being able to stop it.

The analysis is the only part of AutoCut that takes real time, so this screen is
mostly about honesty while waiting: which stage, which file, how long it has been,
how long is left, and a cancel that actually stops. Everything it shows comes from
the progress events the core already emits.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from autocut.core.cache import cache_stats, prune
from autocut.core.events import ProgressEvent
from autocut.core.pipeline import AnalysisOutcome
from autocut.gui import theme
from autocut.gui.state import ProjectState
from autocut.gui.widgets.empty import EmptyState
from autocut.gui.widgets.stages import StageList

#: The stages of one analysis run, in the order the core reports them.
STAGE_TITLES: tuple[tuple[str, str], ...] = (
    ("scan", "Scanning folders"),
    ("probe", "Probing files"),
    ("analyze", "Analyzing frames"),
    ("embed", "Embedding"),
    ("tag", "Tagging"),
    ("describe", "Describing"),
)


def format_seconds(seconds: float) -> str:
    """``m:ss`` for anything under an hour, ``h:mm:ss`` above it."""
    seconds = max(0.0, seconds)
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def estimate_remaining(elapsed: float, current: int, total: int) -> float | None:
    """Seconds left at the rate so far, or ``None`` when there is no rate yet.

    A guess from one file is worse than no guess: the first file of a run pays for
    every warm up there is, and showing "42 minutes left" that becomes four is worse
    than showing nothing for a moment.
    """
    if current < 2 or total <= 0 or elapsed <= 0:
        return None
    return elapsed / current * (total - current)


class AnalysisScreen(QWidget):
    """Steps, a progress bar, the current file, cancel, resume and the summary."""

    open_project_requested = Signal()
    """The empty state's one action: the window sends the user to the Project screen."""

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("screen-analysis")
        self._state = state
        self._started_at = 0.0
        self._stage: str = ""

        self.steps = StageList(STAGE_TITLES)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.current_file = QLabel("Nothing running")
        self.current_file.setTextFormat(Qt.TextFormat.PlainText)
        self.current_file.setProperty("role", "muted")
        self.timing = QLabel()
        self.timing.setFont(theme.font(theme.METRICS.body_size, mono=True))
        self.timing.setProperty("role", "muted")

        self.run_button = QPushButton("Run analysis")
        self.run_button.setProperty("variant", "primary")
        self.run_button.clicked.connect(self.run)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._state.cancel)
        self.clear_cache_button = QPushButton("Clear the analysis cache")
        self.clear_cache_button.clicked.connect(self._clear_cache)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setTextFormat(Qt.TextFormat.PlainText)
        self.warnings.setProperty("role", "warning")

        progress_box = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_box)
        progress_layout.setSpacing(theme.METRICS.space + 2)
        progress_layout.addWidget(self.steps)
        progress_layout.addWidget(self.bar)
        running = QHBoxLayout()
        running.addWidget(self.current_file, 1)
        running.addWidget(self.timing)
        progress_layout.addLayout(running)

        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.clear_cache_button)

        result_box = QGroupBox("Result")
        result_layout = QVBoxLayout(result_box)
        result_layout.addWidget(self.summary)
        result_layout.addWidget(self.warnings)
        result_layout.addStretch(1)

        # Before a project there is nothing to run, so the screen says that and offers
        # the one thing that would change it rather than showing six dead stages.
        self.open_project_button = QPushButton("Open a project…")
        self.open_project_button.setProperty("variant", "primary")
        self.open_project_button.clicked.connect(self.open_project_requested.emit)
        self.empty = EmptyState(
            "No project open. Open or create one and its footage can be analysed.",
            icon="folder",
            action=self.open_project_button,
        )

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(theme.METRICS.space * 2)
        body_layout.addWidget(progress_box)
        body_layout.addLayout(buttons)
        body_layout.addWidget(result_box, 1)

        # The stages, the summary and the warnings all grow with a real run, so the
        # body scrolls rather than setting a floor the window cannot go under.
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body_scroll.setWidget(self.body)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(body_scroll)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(self.stack)

        state.progress.connect(self._on_progress)
        state.stage_started.connect(self._on_started)
        state.stage_finished.connect(self._on_finished)
        state.stage_cancelled.connect(self._on_cancelled)
        state.error.connect(self._on_error)
        state.segments_changed.connect(lambda _ids: self.refresh())
        self.refresh()

    # --- what the button says -----------------------------------------------

    def refresh(self) -> None:
        """Label the run button for what it would actually do, and enable what can run."""
        manifest = self._state.manifest
        running = self._state.is_running
        self.stack.setCurrentIndex(1 if manifest is not None else 0)
        self.run_button.setEnabled(manifest is not None and not running)
        self.cancel_button.setEnabled(running)
        self.clear_cache_button.setEnabled(not running)
        if manifest is None:
            self.run_button.setText("Run analysis")
            self.summary.setText("Open a project first.")
            return
        analyzed = bool(manifest.segments)
        probed = bool(manifest.files)
        if analyzed and self.is_incomplete():
            self.run_button.setText("Resume analysis")
        elif analyzed:
            self.run_button.setText("Re-run analysis")
        else:
            self.run_button.setText("Run analysis")
        if analyzed and not running:
            self.summary.setText(
                f"{len(manifest.segments)} segments from {len(manifest.files)} files. "
                "Running again is cheap: analysed files come from the cache."
            )
        elif probed and not running:
            self.summary.setText(f"{len(manifest.files)} files probed, no segments yet.")

    def is_incomplete(self) -> bool:
        """Whether a previous run stopped early, which is what makes this a resume.

        A file that was probed but produced no segment and no error is a file the
        analysis never reached, which is exactly what a cancel leaves behind.
        """
        manifest = self._state.manifest
        if manifest is None or not manifest.files:
            return False
        with_segments = {segment.file_id for segment in manifest.segments.values()}
        return any(
            source.error is None and source.id not in with_segments
            for source in manifest.files.values()
        )

    # --- running ------------------------------------------------------------

    def run(self) -> bool:
        self.warnings.clear()
        self.bar.setValue(0)
        return self._state.run_analysis()

    def _clear_cache(self) -> None:
        """Drop every cache entry, so the next run recomputes from the footage."""
        removed = prune(self._state.config, older_than_days=0.0)
        stats = cache_stats(self._state.config)
        self.summary.setText(
            f"Removed {removed} cache entries. {stats.entries} left in {stats.directory}."
        )

    def _on_started(self, name: str) -> None:
        self._started_at = time.monotonic()
        self._stage = ""
        self.current_file.setText(f"Starting {name}")
        self.refresh()

    def _on_progress(self, event: object) -> None:
        if not isinstance(event, ProgressEvent):
            return
        if event.stage != self._stage:
            self._stage = event.stage
            self._mark_steps(event.stage)
        if event.total > 0:
            self.bar.setRange(0, event.total)
            self.bar.setValue(event.current)
            self.steps.set_counter(event.stage, f"{event.current} / {event.total}")
        else:
            self.bar.setRange(0, 0)  # An indeterminate stage, so an indeterminate bar.
        name = Path(event.path).name if event.path else event.message
        cached = " (cached)" if event.extra.get("cached") else ""
        title = dict(STAGE_TITLES).get(event.stage, event.stage)
        self.current_file.setText(f"{title}: {name}{cached}" if name else title)
        elapsed = time.monotonic() - self._started_at
        left = estimate_remaining(elapsed, event.current, event.total)
        self.timing.setText(
            f"{format_seconds(elapsed)} elapsed"
            + (f", about {format_seconds(left)} left" if left is not None else "")
        )

    def _mark_steps(self, stage: str) -> None:
        """Tick every stage up to the running one. The core reports them in order."""
        self.steps.mark_up_to(stage)

    def _on_finished(self, name: str) -> None:
        if name != "analysis":
            return
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.steps.mark_all_done()
        elapsed = time.monotonic() - self._started_at
        self.current_file.setText(f"Finished in {format_seconds(elapsed)}")
        self.summary.setText(self.describe_outcome(self._state.last_result))
        self._show_warnings()
        self.refresh()

    def describe_outcome(self, result: object) -> str:
        """The run in a few lines, using the same numbers the CLI prints."""
        manifest = self._state.manifest
        if not isinstance(result, AnalysisOutcome) or manifest is None:
            return ""
        lines = [
            f"{result.segments} segments from {result.files} files "
            f"({result.cached_files} from cache, {result.unreadable} unreadable)."
        ]
        embed = result.embed
        if embed is not None:
            lines.append(
                f"Embeddings skipped: {embed.skipped_reason}."
                if embed.skipped_reason
                else f"Embedded {embed.segments} segments with {embed.model} on {embed.device}."
            )
        tag = result.tag
        if tag is not None:
            lines.append(
                f"Tagging skipped: {tag.skipped_reason}."
                if tag.skipped_reason
                else f"Tagged {tag.with_a_tag} of {tag.embedded} embedded segments."
            )
        describe = result.describe
        if describe is not None:
            lines.append(
                f"Descriptions skipped: {describe.skipped_reason}."
                if describe.skipped_reason
                else f"Described {describe.described} segments in {describe.requests} requests."
            )
        rejected = sum(1 for segment in manifest.segments.values() if segment.reason)
        if rejected:
            lines.append(f"{rejected} segments were rejected by the rules.")
        return "\n".join(lines)

    def _show_warnings(self) -> None:
        manifest = self._state.manifest
        if manifest is None:
            return
        self.warnings.setText("\n".join(manifest.analysis.warnings))

    def _on_cancelled(self, name: str) -> None:
        if name != "analysis":
            return
        self.bar.setRange(0, 100)
        self.current_file.setText("Cancelled. What was analysed is saved and can be resumed.")
        self._show_warnings()
        self.refresh()

    def _on_error(self, message: str) -> None:
        self.bar.setRange(0, 100)
        self.current_file.setText(message)
        self.refresh()

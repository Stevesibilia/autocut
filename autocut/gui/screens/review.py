"""Screen 3: the central screen, where a person corrects the machine.

Everything on it exists to make one loop short: look at a clip, decide, see the edit
change. The grid, the preview and the sliders are separate widgets so each can be
tested alone; this module is the wiring, the filters and the header, and it owns the
keyboard, because the two minute review of SPEC.md section 11 is a keyboard review.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from autocut.core.durations import total_duration
from autocut.core.manifest import Manifest
from autocut.core.montage import MontageResult, discard
from autocut.core.report import render_report
from autocut.core.rules import EXCLUSIONS
from autocut.gui import theme
from autocut.gui.state import ProjectState
from autocut.gui.widgets.chips import FilterChips
from autocut.gui.widgets.empty import EmptyState
from autocut.gui.widgets.groups import GroupsView, groups_summary
from autocut.gui.widgets.montage import MontagePlayer, clip_labels
from autocut.gui.widgets.preview import PreviewPanel
from autocut.gui.widgets.sliders import SliderPanel
from autocut.gui.widgets.thumb_grid import ThumbGrid
from autocut.gui.widgets.topbar import Counter, edit_counters

ANY = "any"


class ReviewScreen(QWidget):
    """Filters and header on top, grid or groups on the left, preview and sliders right."""

    report_written = Signal(str)
    open_project_requested = Signal()
    """The empty state's one action: the window sends the user to the Project screen."""

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("screen-review")
        self._state = state

        self.grid = ThumbGrid(state, self)
        self.groups = GroupsView(state, self)
        self.montage = MontagePlayer(self)
        # Shown instead of the grid when there is nothing to review: one sentence and
        # the one thing that would fix it, which here is opening a project.
        self.open_project_button = QPushButton("Open a project…")
        self.open_project_button.setProperty("variant", "primary")
        self.open_project_button.clicked.connect(self.open_project_requested.emit)
        self.empty = EmptyState(
            "No project open. Open one and analyse it to review its clips.",
            icon="folder",
            action=self.open_project_button,
        )

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.groups)
        self.stack.addWidget(self.montage)

        self.preview = PreviewPanel(state, self)
        self.sliders = SliderPanel(state, self)
        metrics = theme.current().metrics

        # --- notices ---------------------------------------------------------
        # The counters live in the window's top bar now: they are about the project and
        # every screen wants to read them. What is left here is what only this screen
        # can say, which is when the edit disagrees with the settings.
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setProperty("role", "warning")

        # --- filters --------------------------------------------------------
        self.sort_box = QComboBox()
        self.sort_box.addItem("Chronology", "time")
        self.sort_box.addItem("Score", "score")
        self.sort_box.currentIndexChanged.connect(self._sort_changed)

        self.class_box = QComboBox()
        self.tag_box = QComboBox()
        self.place_box = QComboBox()
        self.outcome_box = QComboBox()
        self.reason_box = QComboBox()
        for box in (self.class_box, self.tag_box, self.place_box, self.outcome_box):
            box.currentIndexChanged.connect(self._filters_changed)
        self.reason_box.currentIndexChanged.connect(self._filters_changed)

        self.min_score = QDoubleSpinBox()
        self.max_score = QDoubleSpinBox()
        for spin, value in ((self.min_score, 0.0), (self.max_score, 1.0)):
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setValue(value)
            spin.valueChanged.connect(self._filters_changed)

        self.show_rejected = QCheckBox("Show clips the rules rejected")
        self.show_rejected.toggled.connect(self._filters_changed)

        self.groups_toggle = QCheckBox("Similar groups")
        self.groups_toggle.toggled.connect(self._mode_changed)

        self.play_all_button = QPushButton("Play all")
        self.play_all_button.clicked.connect(self.play_all)
        self.montage_note = QLabel()
        self.montage_note.setWordWrap(True)
        self.montage_note.setProperty("role", "muted")

        self.keep_button = QPushButton("Keep (K)")
        self.reject_button = QPushButton("Reject (R)")
        self.clear_button = QPushButton("Clear")
        self.undo_button = QPushButton("Undo (U)")
        self.report_button = QPushButton("Export report")
        self.keep_button.clicked.connect(lambda: self._decide("keep"))
        self.reject_button.clicked.connect(lambda: self._decide("reject"))
        self.clear_button.clicked.connect(lambda: self._decide(None))
        self.undo_button.clicked.connect(self.undo)
        self.report_button.clicked.connect(self.export_report)

        # The boxes above are the filter model and stay exactly as they were; the chips
        # are a face over them, so the proxy and everything that drives a box directly
        # are untouched. The boxes themselves are never shown.
        self.filters = FilterChips()
        self.filters.add_box("sort", "Sort", self.sort_box)
        for key, label, box in (
            ("class", "Class", self.class_box),
            ("tag", "Tag", self.tag_box),
            ("place", "Place", self.place_box),
            ("outcome", "Outcome", self.outcome_box),
            ("reason", "Reason", self.reason_box),
        ):
            self.filters.add_box(key, label, box)
        self.filters.add_range("score", "Score", self.min_score, self.max_score)
        self.filters.add_toggle(self.show_rejected)
        self.filters.add_toggle(self.groups_toggle)

        # Play all and Export report are handed to the top bar by bar_actions; what
        # stays here is the decision row, which belongs beside the grid it acts on.
        actions = QHBoxLayout()
        actions.addWidget(self.keep_button)
        actions.addWidget(self.reject_button)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.undo_button)
        actions.addStretch(1)

        # The right panel, in the order the spec fixes: the file and its preview, the
        # bounds and the two actions on them, then diversity, then the weights, and last
        # a line about what the caps held back. It scrolls, because six weight sliders
        # and a preview do not fit a laptop at the panel's fixed width.
        self.groups_summary = QLabel("")
        self.groups_summary.setWordWrap(True)
        self.groups_summary.setProperty("role", "muted")
        summary_heading = QLabel("Similar groups")
        summary_heading.setProperty("role", "label")

        panel_body = QWidget()
        panel_layout = QVBoxLayout(panel_body)
        panel_layout.setContentsMargins(20, 18, 20, 18)
        panel_layout.setSpacing(metrics.space * 2)
        panel_layout.addWidget(self.preview)
        panel_layout.addWidget(self.sliders)
        panel_layout.addStretch(1)
        panel_layout.addWidget(summary_heading)
        panel_layout.addWidget(self.groups_summary)

        self.panel = QScrollArea()
        self.panel.setObjectName("rightPanel")
        self.panel.setWidgetResizable(True)
        self.panel.setFrameShape(QScrollArea.Shape.NoFrame)
        self.panel.setFixedWidth(metrics.panel_width)
        self.panel.setWidget(panel_body)

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(metrics.space * 3, 14, metrics.space * 3, 0)
        centre_layout.setSpacing(metrics.space + 4)
        centre_layout.addWidget(self.filters)
        centre_layout.addWidget(self.warning)
        centre_layout.addWidget(self.montage_note)
        centre_layout.addWidget(self.stack, 1)
        centre_layout.addLayout(actions)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(centre, 1)
        layout.addWidget(self.panel)

        # --- wiring ---------------------------------------------------------
        self.grid.keep_requested.connect(lambda sid: self._decide("keep", sid))
        self.grid.reject_requested.connect(lambda sid: self._decide("reject", sid))
        self.grid.toggle_requested.connect(self._toggle)
        self.grid.undo_requested.connect(self.undo)
        self.grid.current_segment_changed.connect(self.preview.show_segment)
        self.grid.activated_segment.connect(self._activate)
        self.preview.bounds_committed.connect(self._bounds_committed)
        self.groups.swap_requested.connect(self._swap)
        self.montage.clip_changed.connect(self._montage_clip_changed)
        self.montage.boundary_clicked.connect(self._montage_clip_changed)

        state.selection_changed.connect(self._selection_changed)
        state.segments_changed.connect(lambda _ids: self.refresh_header())
        state.project_changed.connect(self.reload)
        state.stage_started.connect(lambda _name: self._set_running(True))
        state.stage_finished.connect(self._stage_finished)
        state.stage_cancelled.connect(lambda _name: self._set_running(False))
        # Also on error: a failed stage emits neither finished nor cancelled, and
        # without this the screen stayed disabled until the next stage ran.
        state.error.connect(lambda _message: self._set_running(False))

        self.reload()

    # --- filling in what the project offers --------------------------------

    def reload(self) -> None:
        """Rebuild the filter choices and the header for the project now open."""
        manifest = self._state.manifest
        self.sliders.adopt_config()
        self.grid.delegate.clear_caches()
        self._fill_filters(manifest)
        self.groups.refresh()
        self.refresh_header()
        self.groups_summary.setText(groups_summary(manifest))
        self._show_grid_or_empty()
        if manifest is not None and self.grid.count and not self.grid.current_id():
            self.grid.setCurrentIndex(self.grid.proxy.index(0, 0))

    def _fill_filters(self, manifest: Manifest | None) -> None:
        """Rebuild the filter choices, keeping whatever the user had picked.

        Called on open and after every selection, because places and clusters are
        assigned by selection: before the first one the place filter has nothing to
        offer, and a screen that only filled it on open would never show it at all.
        """
        chosen = {
            box: box.currentData()
            for box in (
                self.class_box,
                self.tag_box,
                self.place_box,
                self.outcome_box,
                self.reason_box,
            )
        }
        self._rebuild_filters(manifest)
        for box, value in chosen.items():
            if value is None:
                continue
            index = box.findData(value)
            if index >= 0:
                box.blockSignals(True)
                box.setCurrentIndex(index)
                box.blockSignals(False)
        # The blocked signals above are how the boxes keep the proxy from re-filtering
        # six times per project open, so the chips have to be told by hand instead.
        self.filters.refresh()

    def _rebuild_filters(self, manifest: Manifest | None) -> None:
        classes = sorted(
            {source.source_class for source in (manifest.files.values() if manifest else [])}
        )
        tags = sorted(
            {
                tag.label
                for segment in (manifest.segments.values() if manifest else [])
                for tag in segment.tags
            }
        )
        places = sorted(
            {
                segment.place_id
                for segment in (manifest.segments.values() if manifest else [])
                if segment.place_id is not None
            }
        )
        reasons = sorted(
            {
                segment.reason
                for segment in (manifest.segments.values() if manifest else [])
                if segment.reason
            }
        )
        # ``places`` is keyed by the place id as a string, because JSON keys are strings.
        place_names = {
            place.place_id: place.label for place in (manifest.places.values() if manifest else [])
        }

        for box, values, labels in (
            (self.class_box, classes, [str(value) for value in classes]),
            (self.tag_box, tags, [str(value) for value in tags]),
            (
                self.place_box,
                places,
                [place_names.get(value, f"place {value}") for value in places],
            ),
            (
                self.outcome_box,
                ["selected", "candidate", "rejected"],
                ["selected", "candidate", "rejected"],
            ),
            (self.reason_box, reasons, [str(value) for value in reasons]),
        ):
            box.blockSignals(True)
            box.clear()
            box.addItem(ANY, None)
            for value, label in zip(values, labels, strict=True):
                box.addItem(label, value)
            box.blockSignals(False)

    # --- header ------------------------------------------------------------

    def bar_counters(self) -> list[Counter]:
        """The edit, counted for the top bar: project wide, whatever the filters show.

        Project wide on purpose. The counters answer "how long is my edit", and a
        number that changed when a filter changed would answer nothing.
        """
        manifest = self._state.manifest
        if manifest is None:
            return []
        selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
        return edit_counters(
            clips=len(selected),
            duration_s=total_duration(selected),
            # The synced tempo, not the measured one: a measurement is not a sync,
            # and the counter is about the edit the clips were actually cut to.
            bpm=round(manifest.soundtrack.synced_bpm) if manifest.soundtrack.synced_bpm else None,
            kept=sum(1 for s in manifest.segments.values() if s.kept),
            rejected=sum(1 for s in manifest.segments.values() if s.user_rejected),
        )

    def bar_actions(self) -> list[QWidget]:
        """The two things this screen does that are about the whole edit."""
        return [self.play_all_button, self.report_button]

    def refresh_header(self) -> None:
        """The one notice only this screen can give: the edit against the settings."""
        manifest = self._state.manifest
        if manifest is None:
            self.warning.clear()
            return
        kept = sum(1 for s in manifest.segments.values() if s.kept)
        cap = self._state.config.selection.max_clips
        if kept > cap:
            self.warning.setText(
                f"{kept} clips are kept by hand and the maximum is {cap}, so the edit is "
                "longer than the settings ask for. Pins are never dropped for a cap."
            )
        else:
            self.warning.clear()

    # --- decisions ---------------------------------------------------------

    def _current(self, segment_id: str = "") -> str:
        """Which clip a decision is about.

        The clip on screen wins while the montage is playing: pressing R during
        playback is a judgement about what is being watched, not about whatever the
        grid cursor was left on.
        """
        if segment_id:
            return segment_id
        if self.stack.currentWidget() is self.montage:
            playing = self.montage.current_segment_id()
            if playing:
                return playing
        return self.grid.current_id()

    def _decide(self, decision: str | None, segment_id: str = "") -> None:
        target = self._current(segment_id)
        if not target:
            return
        row = self.grid.proxy.mapFromSource(
            self.grid.model_source.index(self.grid.model_source.row_of(target), 0)
        ).row()
        self._state.set_decision(target, decision)  # type: ignore[arg-type]
        # Keep the cursor where the hand is: after a decision the grid reorders, and a
        # reviewer working through it should land on the next card, not back at the top.
        self._restore_cursor(target, row)
        self._montage_stale()

    def _toggle(self, segment_id: str) -> None:
        target = self._current(segment_id)
        if target:
            self._state.toggle_keep(target)

    def _restore_cursor(self, segment_id: str, previous_row: int) -> None:
        if self.grid.select_segment(segment_id):
            return
        if previous_row >= 0 and self.grid.count:
            self.grid.setCurrentIndex(
                self.grid.proxy.index(min(previous_row, self.grid.count - 1), 0)
            )

    def undo(self) -> None:
        if self._state.undo_stack.canUndo():
            self._state.undo_stack.undo()

    def redo(self) -> None:
        if self._state.undo_stack.canRedo():
            self._state.undo_stack.redo()

    def _bounds_committed(self, segment_id: str, bounds: object) -> None:
        """The preview hands over a pair or ``None``; the signal cannot say which."""
        if not isinstance(bounds, tuple) or len(bounds) != 2:
            self._state.set_user_bounds(segment_id, None)
            return
        self._state.set_user_bounds(segment_id, (float(bounds[0]), float(bounds[1])))

    def _swap(self, keep_id: str, reject_id: str) -> None:
        self._state.swap_pick(keep_id, reject_id)

    def _activate(self, segment_id: str) -> None:
        """Double click or Return: put the clip in the preview and focus the bounds."""
        self.preview.show_segment(segment_id)
        self.preview.start_slider.setFocus()

    # --- reacting ----------------------------------------------------------

    def _selection_changed(self) -> None:
        current = self.grid.current_id()
        self._fill_filters(self._state.manifest)
        self.groups.refresh()
        self.refresh_header()
        self.groups_summary.setText(groups_summary(self._state.manifest))
        if current:
            self.grid.select_segment(current)
        self.preview.show_segment(self.grid.current_id())

    def _sort_changed(self) -> None:
        if self.sort_box.currentData() == "score":
            self.grid.proxy.sort_by_score()
        else:
            self.grid.proxy.sort_by_chronology()
        self.refresh_header()

    def _filters_changed(self) -> None:
        proxy = self.grid.proxy
        source_class = self.class_box.currentData()
        proxy.set_source_classes({str(source_class)} if source_class else set())
        proxy.set_tag(str(self.tag_box.currentData() or ""))
        place = self.place_box.currentData()
        proxy.set_place(int(place) if place is not None else None)
        outcome = self.outcome_box.currentData()
        proxy.set_outcomes({outcome} if outcome else set())
        reason = self.reason_box.currentData()
        proxy.set_reasons({str(reason)} if reason else set())
        proxy.set_score_range(self.min_score.value(), self.max_score.value())
        # An outcome or reason filter for the rejected implies showing them, or the
        # filter would select a set the grid then hides.
        wants_rejected = outcome == "rejected" or (reason is not None and reason not in EXCLUSIONS)
        proxy.set_show_rejected(self.show_rejected.isChecked() or bool(wants_rejected))
        self.refresh_header()

    def _mode_changed(self, groups: bool) -> None:
        """Groups replaces the grid. Leaving the montage is what stops it."""
        if self.stack.currentWidget() is self.montage:
            self.montage.pause()
        self.stack.setCurrentWidget(self.groups if groups else self.grid)
        if groups:
            self.groups.refresh()

    def _show_grid_or_empty(self) -> None:
        """The grid when there is a project, the empty state when there is not."""
        if self._state.manifest is None:
            self.stack.setCurrentWidget(self.empty)
        elif self.stack.currentWidget() is self.empty:
            self.stack.setCurrentWidget(self.grid)

    def _set_running(self, running: bool) -> None:
        """No decisions while a stage owns the manifest."""
        for widget in (
            self.keep_button,
            self.reject_button,
            self.clear_button,
            self.undo_button,
            self.report_button,
            self.play_all_button,
            self.sliders,
            self.grid,
        ):
            widget.setEnabled(not running)

    def _stage_finished(self, name: str) -> None:
        self._set_running(False)
        if name != "montage":
            return
        result = self._state.last_result
        if isinstance(result, MontageResult) and result.ok:
            if self._show_montage():
                self.montage.play()
            # Only now, with the player pointed at the new file: deleting the old one
            # before that is deleting a file something is reading.
            discard(result.previous)
            return
        reason = ""
        if isinstance(result, MontageResult):
            reason = result.skipped_reason or "; ".join(
                f"{segment_id}: {error}" for segment_id, error in result.errors
            )
        self.montage_note.setText(reason or "The montage could not be built.")

    # --- the montage -------------------------------------------------------

    def play_all(self) -> bool:
        """Watch the whole edit. Renders it first when the edit has changed.

        The montage is the only thing on this screen that costs real time, so it goes
        through the worker; when the fingerprint still matches, the stage finds the
        file already there and returns without rendering.
        """
        state = self._state
        if state.manifest is None or state.is_running:
            return False
        track = self._track_path()
        if state.montage_is_current(track) and self._show_montage():
            self.montage.play()
            return True
        # Let go of the file before anything writes near it: the player keeps the mp4
        # open, and a rebuild used to leave it decoding a file that had changed under
        # it, which is a black picture and a stream of NAL unit errors.
        self.montage.clear()
        self.montage_note.setText("Building the montage from the selected clips…")
        return state.run_montage(track=track)

    def _track_path(self) -> Path | None:
        """The track the project loaded, when there is one, so the montage carries it."""
        manifest = self._state.manifest
        if manifest is None or manifest.soundtrack.audio_path is None:
            return None
        path = Path(manifest.soundtrack.audio_path)
        return path if path.exists() else None

    def _show_montage(self) -> bool:
        """Load the rendered montage into the player and bring it to the front."""
        manifest = self._state.manifest
        if manifest is None or manifest.preview.path is None:
            return False
        path = Path(manifest.preview.path)
        index = Path(manifest.preview.index_path) if manifest.preview.index_path else None
        if not self.montage.load(
            path,
            index,
            sound=manifest.preview.has_audio,
            labels=clip_labels(manifest),
        ):
            self.montage_note.setText("The montage file is gone. Press Play all to build it.")
            return False
        self.groups_toggle.setChecked(False)
        self.stack.setCurrentWidget(self.montage)
        # The montage's own length belongs in the transport row, which says it. The
        # header above says how long the edit is, and two different durations one line
        # apart read as one number contradicting itself.
        self.montage_note.setText(
            f"Montage of {manifest.preview.clips} clips"
            + (" with the track" if manifest.preview.has_audio else "")
            + ". K, R, space and U apply to the clip playing."
        )
        return True

    def show_grid(self) -> None:
        self.montage.pause()
        self.groups_toggle.setChecked(False)
        self.stack.setCurrentWidget(self.grid)

    def _montage_clip_changed(self, segment_id: str) -> None:
        """Follow the montage in the grid, so a decision lands on what is on screen."""
        if not segment_id:
            return
        self.grid.select_segment(segment_id)
        self.preview.show_segment(segment_id)

    def _montage_stale(self) -> None:
        """Say that the montage no longer matches the edit, without interrupting it.

        Stopping playback on a decision would make reviewing while watching useless,
        which is the whole point of routing the keys to the playing clip.
        """
        if self.montage.path is None:
            return
        self.montage_note.setText(
            "The montage no longer matches the edit. Press Play all to build it again."
        )

    # --- the report --------------------------------------------------------

    def export_report(self) -> Path | None:
        """Write ``report.html`` from the state, so the CLI report shows the review."""
        manifest = self._state.manifest
        if manifest is None or self._state.output_dir is None or self._state.is_running:
            return None
        self._state.save_now()
        path = render_report(manifest, self._state.output_dir)
        self.report_written.emit(str(path))
        return path

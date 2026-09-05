"""Screen 5: the folder that goes to CapCut.

Every option here already exists in the configuration and on the command line. What
the screen adds is that they are visible at once, that the per class ones are a grid
rather than a nest of dotted keys, and that the answer to "what will this actually
do" is on screen before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from autocut.core.config import SOURCE_CLASSES, AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent
from autocut.core.export import ExportResult, export_clips
from autocut.core.ffmpeg_cmd import (
    ExportOverrides,
    common_frame,
    resolve_target_fps,
    slow_motion_ratio,
)
from autocut.core.manifest import Manifest
from autocut.core.montage import clear_preview, is_current
from autocut.core.naming import SELECTS_DIR, STALE_DIR
from autocut.core.render import RenderResult, render_edit, render_path, resolve_track
from autocut.gui import theme
from autocut.gui.settings import write_config
from autocut.gui.state import ProjectState
from autocut.gui.widgets.chips import FilterChips

#: The export fields the screen writes back to ``autocut.toml``. The per class ones are
#: written whole, since a table with one key changed is still the whole table.
EXPORT_PATHS: tuple[str, ...] = (
    "export.mode",
    "export.codec",
    "export.crf",
    "export.fps",
    "export.max_width",
    "export.max_height",
    "export.vertical_strategy",
    "export.keep_rejects",
    "export.remove_audio",
    "export.slow_motion_auto",
    "export.lens_correction",
    "export.lut",
    "render.enabled",
    "render.fade_out_seconds",
)


@dataclass(slots=True)
class ExportOutcome:
    """What one press of Export produced: the clips, and the render when asked for.

    One stage runs both, because the render's input is the export and a second
    ``run_stage`` would be refused while the first worker is still winding down.
    """

    export: ExportResult
    render: RenderResult | None = None


def folder_size(path: Path) -> int:
    """Bytes under a folder, ignoring what cannot be read."""
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def short_path(path: Path, keep: int = 2) -> str:
    """The last `keep` parts of `path`, so a deep project folder still fits the card.

    An absolute path has no spaces in it, so a word wrapped label asks for its whole
    length and takes the screen with it. The full path lives on the tooltip.
    """
    shortened = "…/" + "/".join(path.parts[-keep:])
    # A path that is already short gains nothing from an ellipsis and loses the root.
    return str(path) if len(shortened) >= len(str(path)) else shortened


#: Wide enough for a frame height and no wider.
NUMBER_FIELD_WIDTH = 96
#: The LUT path is the one field on the screen that is worth stretching.
LUT_FIELD_WIDTH = 260


class ExportScreen(QWidget):
    """The options, a dry run summary, the progress, and the folder at the end."""

    exported = Signal()

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("screen-export")
        self._state = state
        self._result: ExportResult | None = None
        self._render: RenderResult | None = None

        # --- the options ------------------------------------------------------
        self.mode_box = QComboBox()
        self.mode_box.addItems(["precise", "fast"])
        self.codec_box = QComboBox()
        self.codec_box.addItems(["libx264", "libx265", "h264_videotoolbox", "h264_vaapi"])
        self.crf_field = QSpinBox()
        self.crf_field.setRange(0, 51)
        self.fps_field = QDoubleSpinBox()
        self.fps_field.setRange(0.0, 240.0)
        self.fps_field.setDecimals(3)
        self.fps_field.setSpecialValueText("auto")
        self.width_field = QSpinBox()
        self.width_field.setRange(320, 7680)
        self.height_field = QSpinBox()
        self.height_field.setRange(240, 4320)
        self.vertical_box = QComboBox()
        self.vertical_box.addItems(["exclude", "center_crop", "blur_pad", "keep"])
        self.rejects_box = QCheckBox("Also export the rejected clips")
        self.render_box = QCheckBox("Also render the montage with the track (hard cuts)")
        self.fade_field = QDoubleSpinBox()
        self.fade_field.setRange(0.0, 30.0)
        self.fade_field.setDecimals(1)
        self.fade_field.setSingleStep(0.5)
        self.fade_field.setSuffix(" s")

        # The three choices that decide what kind of export this is are chips, because
        # they are picked once and then read at a glance; the numbers stay a form.
        self.profile = FilterChips()
        self.profile.add_box("mode", "Cut", self.mode_box)
        self.profile.add_box("codec", "Codec", self.codec_box)
        self.profile.add_box("vertical", "Vertical", self.vertical_box)

        # A number is four characters wide. Left to itself a QFormLayout gives the field
        # column every pixel that is going, and a CRF box a thousand pixels wide reads
        # as a text area someone forgot to fill in.
        for number in (self.crf_field, self.fps_field, self.width_field, self.height_field):
            number.setFixedWidth(NUMBER_FIELD_WIDTH)
        self.fade_field.setFixedWidth(NUMBER_FIELD_WIDTH)

        form = QFormLayout()
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.addRow("Quality (CRF)", self.crf_field)
        form.addRow("Target fps", self.fps_field)
        form.addRow("Maximum width", self.width_field)
        form.addRow("Maximum height", self.height_field)
        form.addRow("", self.rejects_box)

        options_box = QGroupBox("Output")
        options_layout = QVBoxLayout(options_box)
        options_layout.setSpacing(theme.METRICS.space + 2)
        options_layout.addWidget(self.profile)
        options_layout.addLayout(form)

        # The final render is a decision of its own, not one more row of the export
        # form: it produces a different file, in a different place, from a different
        # input. Its own card says so.
        self.frame_label = QLabel()
        self.frame_label.setTextFormat(Qt.TextFormat.PlainText)
        self.frame_label.setProperty("role", "muted")
        self.destination_label = QLabel("")
        self.destination_label.setProperty("role", "muted")
        self.destination_label.setTextFormat(Qt.TextFormat.PlainText)
        self.destination_label.setWordWrap(True)

        fade_label = QLabel("Fade out")
        fade_label.setProperty("role", "label")
        fade_row = QHBoxLayout()
        fade_row.setSpacing(theme.METRICS.space)
        fade_row.addWidget(fade_label)
        fade_row.addWidget(self.fade_field)
        fade_row.addStretch(1)

        self.render_card = QWidget()
        self.render_card.setObjectName("card")
        render_layout = QVBoxLayout(self.render_card)
        render_layout.setContentsMargins(14, 12, 14, 12)
        render_layout.setSpacing(theme.METRICS.space)
        render_layout.addWidget(self.render_box)
        render_layout.addLayout(fade_row)
        render_layout.addWidget(self.destination_label)
        render_layout.addWidget(self.frame_label)

        # --- per class --------------------------------------------------------
        self.audio_boxes: dict[str, QCheckBox] = {}
        self.slow_boxes: dict[str, QCheckBox] = {}
        self.lens_boxes: dict[str, QCheckBox] = {}
        self.lut_fields: dict[str, QLineEdit] = {}
        grid = QGridLayout()
        for column, header in enumerate(("Class", "Keep audio", "Slow motion", "Lens", "LUT")):
            label = QLabel(header)
            label.setProperty("role", "title")
            # The three middle columns are checkboxes, which Qt draws at their own
            # width: centred under the header they belong to rather than left against
            # the name of the class in the column before.
            grid.addWidget(
                label,
                0,
                column,
                alignment=Qt.AlignmentFlag.AlignCenter
                if 0 < column < 4
                else Qt.AlignmentFlag.AlignLeft,
            )
        grid.setColumnMinimumWidth(0, 90)
        # The class column takes the slack, not the LUT path: a row of checkboxes
        # pushed to the far right of a wide window is a row nobody can follow back to
        # the class it belongs to.
        grid.setColumnStretch(5, 1)
        for row, source_class in enumerate(SOURCE_CLASSES, start=1):
            grid.addWidget(QLabel(source_class), row, 0)
            keep_audio = QCheckBox()
            slow = QCheckBox()
            lens = QCheckBox()
            lut = QLineEdit()
            lut.setPlaceholderText("none")
            lut.setFixedWidth(LUT_FIELD_WIDTH)
            browse = QPushButton("…")
            # Compact: the shared button rule pads by 14 px a side, which left a 30 px
            # button with no room at all for the character on it.
            browse.setProperty("variant", "compact")
            browse.setFixedWidth(36)
            browse.clicked.connect(lambda _checked=False, name=source_class: self._browse_lut(name))
            for column, box in ((1, keep_audio), (2, slow), (3, lens)):
                grid.addWidget(box, row, column, alignment=Qt.AlignmentFlag.AlignCenter)
            holder = QHBoxLayout()
            holder.addWidget(lut)
            holder.addWidget(browse)
            wrapper = QWidget()
            wrapper.setLayout(holder)
            grid.addWidget(wrapper, row, 4, alignment=Qt.AlignmentFlag.AlignLeft)
            self.audio_boxes[source_class] = keep_audio
            self.slow_boxes[source_class] = slow
            self.lens_boxes[source_class] = lens
            self.lut_fields[source_class] = lut

        per_class_box = QGroupBox("Per source class")
        per_class_layout = QVBoxLayout(per_class_box)
        per_class_layout.addLayout(grid)

        for widget in (
            self.mode_box,
            self.codec_box,
            self.vertical_box,
        ):
            widget.currentIndexChanged.connect(self._options_changed)
        for spin in (self.crf_field, self.width_field, self.height_field):
            spin.valueChanged.connect(self._options_changed)
        self.fps_field.valueChanged.connect(self._options_changed)
        self.rejects_box.toggled.connect(self._options_changed)
        self.render_box.toggled.connect(self._options_changed)
        self.fade_field.valueChanged.connect(self._options_changed)
        for boxes in (self.audio_boxes, self.slow_boxes, self.lens_boxes):
            for box in boxes.values():
                box.toggled.connect(self._options_changed)
        for field in self.lut_fields.values():
            field.textChanged.connect(self._options_changed)

        # --- run --------------------------------------------------------------
        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        self.plan_label.setTextFormat(Qt.TextFormat.PlainText)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.current_label = QLabel("Nothing running")
        self.current_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setTextFormat(Qt.TextFormat.PlainText)
        self.problems.setProperty("role", "error")

        self.run_button = QPushButton("Export")
        self.run_button.clicked.connect(self.run)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(state.cancel)
        self.open_button = QPushButton("Open the folder")
        self.open_button.clicked.connect(self.open_folder)
        self.render_button = QPushButton("Open the render")
        self.render_button.setEnabled(False)
        self.render_button.clicked.connect(self.open_render)
        self.stale_button = QPushButton("Delete the stale files")
        self.stale_button.setEnabled(False)
        # Through a lambda for the same reason as the Play buttons, and it matters more
        # here: connected directly, clicked(False) landed in `confirm` and the button
        # deleted the stale files without ever asking.
        self.stale_button.clicked.connect(lambda: self.delete_stale())

        actions = QHBoxLayout()
        actions.addWidget(self.run_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.stale_button)
        actions.addWidget(self.render_button)
        actions.addWidget(self.open_button)

        run_box = QGroupBox("Run")
        run_layout = QVBoxLayout(run_box)
        run_layout.addWidget(self.plan_label)
        run_layout.addWidget(self.bar)
        run_layout.addWidget(self.current_label)
        run_layout.addLayout(actions)
        run_layout.addWidget(self.summary)
        run_layout.addWidget(self.problems)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.addWidget(options_box)
        body_layout.addWidget(self.render_card)
        body_layout.addWidget(per_class_box)
        body_layout.addWidget(run_box)
        body_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(scroll)

        state.project_changed.connect(self.reload)
        state.selection_changed.connect(self.refresh_plan)
        state.progress.connect(self._on_progress)
        state.stage_started.connect(lambda _name: self._set_running(True))
        state.stage_finished.connect(self._stage_finished)
        state.stage_cancelled.connect(self._stage_cancelled)
        # Also on error: a failed stage emits neither finished nor cancelled, and
        # without this the screen stayed disabled until the next stage ran.
        state.error.connect(lambda _message: self._set_running(False))

        self._loading = False
        self.reload()

    # --- the options -------------------------------------------------------

    def reload(self) -> None:
        """Read every field from the configuration of the project now open."""
        export = self._state.config.export
        self._loading = True
        try:
            self.mode_box.setCurrentText(export.mode)
            self.codec_box.setCurrentText(export.codec)
            self.crf_field.setValue(export.crf)
            self.fps_field.setValue(0.0 if export.fps == "auto" else float(export.fps))
            self.width_field.setValue(export.max_width)
            self.height_field.setValue(export.max_height)
            self.vertical_box.setCurrentText(export.vertical_strategy)
            self.rejects_box.setChecked(export.keep_rejects)
            self.render_box.setChecked(self._state.config.render.enabled)
            self.fade_field.setValue(self._state.config.render.fade_out_seconds)
            self.fade_field.setEnabled(self._state.config.render.enabled)
            for source_class in SOURCE_CLASSES:
                # The config asks whether to remove the audio; the screen asks whether
                # to keep it, which is the question a person actually has.
                self.audio_boxes[source_class].setChecked(not export.remove_audio.get(source_class))
                self.slow_boxes[source_class].setChecked(
                    bool(export.slow_motion_auto.get(source_class))
                )
                self.lens_boxes[source_class].setChecked(
                    bool(export.lens_correction.get(source_class))
                )
                lut = export.lut.get(source_class)
                self.lut_fields[source_class].setText(str(lut) if lut else "")
        finally:
            self._loading = False
        self.refresh_plan()
        self.refresh_stale()

    def _options_changed(self) -> None:
        if self._loading:
            return
        self.apply_options()
        self.refresh_plan()

    def apply_options(self) -> None:
        """Write the fields into the configuration and into ``autocut.toml``."""
        export = self._state.config.export
        export.mode = self.mode_box.currentText()  # type: ignore[assignment]
        export.codec = self.codec_box.currentText()  # type: ignore[assignment]
        export.crf = self.crf_field.value()
        export.fps = "auto" if self.fps_field.value() <= 0 else self.fps_field.value()
        export.max_width = self.width_field.value()
        export.max_height = self.height_field.value()
        export.vertical_strategy = self.vertical_box.currentText()  # type: ignore[assignment]
        export.keep_rejects = self.rejects_box.isChecked()
        render = self._state.config.render
        render.enabled = self.render_box.isChecked()
        render.fade_out_seconds = self.fade_field.value()
        self.fade_field.setEnabled(render.enabled)
        for source_class in SOURCE_CLASSES:
            setattr(
                export.remove_audio,
                source_class,
                not self.audio_boxes[source_class].isChecked(),
            )
            setattr(
                export.slow_motion_auto, source_class, self.slow_boxes[source_class].isChecked()
            )
            setattr(export.lens_correction, source_class, self.lens_boxes[source_class].isChecked())
            text = self.lut_fields[source_class].text().strip()
            setattr(export.lut, source_class, Path(text) if text else None)
        path = self._state.config_path
        if path is not None:
            write_config(self._state.config, path, EXPORT_PATHS)
        self._state.refresh_config_snapshot()

    def _browse_lut(self, source_class: str) -> None:
        name, _filter = QFileDialog.getOpenFileName(
            self, f"LUT for {source_class}", "", "LUT (*.cube *.3dl);;All files (*)"
        )
        if name:
            self.lut_fields[source_class].setText(name)

    # --- the dry run -------------------------------------------------------

    def refresh_plan(self) -> None:
        """What this export would do, from the same code that will do it."""
        manifest = self._state.manifest
        if manifest is None:
            self.plan_label.setText("Open a project first.")
            self.run_button.setEnabled(False)
            return
        config = self._state.config
        selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
        self.run_button.setEnabled(bool(selected) and not self._state.is_running)
        if not selected:
            self.plan_label.setText("Nothing is selected. Review the clips first.")
            return
        target_fps = resolve_target_fps(manifest, config, self._overrides())
        slowed = 0
        converted = 0
        for segment in selected:
            source = manifest.files.get(segment.file_id)
            if source is None:
                continue
            if slow_motion_ratio(source, target_fps, config) > 1:
                slowed += 1
            elif abs(source.fps - target_fps) > 0.01:
                converted += 1
        synced = sum(1 for segment in selected if segment.beats is not None)
        total = sum(segment.target_duration_s or 0.0 for segment in selected)
        lines = [
            f"{len(selected)} clips, {total:.1f} s, at {target_fps:g} fps "
            f"({self.mode_box.currentText()} cut, {self.codec_box.currentText()})",
            f"{slowed} slowed down, {converted} resampled from another frame rate",
        ]
        if synced:
            lines.append(f"{synced} clips are cut to the beat grid")
        else:
            lines.append("No beat sync yet: lengths come from the selection")
        if self.render_box.isChecked():
            track = resolve_track(manifest)
            name = track.name if track is not None else "no track, so the clips' own sound"
            lines.append(
                f"Then {render_path(manifest, config).name} with {name}, "
                f"{self.fade_field.value():g} s fade out"
            )
        self.plan_label.setText("\n".join(lines))
        self.refresh_frame()

    def refresh_frame(self) -> None:
        """Say what one size the clips will come out at, and what it costs.

        Only when a render is asked for: the frame is the smallest clip in the edit, so
        one 720p clip pulls the whole render down to 720p, and a reviewer who can see
        that can drop the clip instead.
        """
        manifest = self._state.manifest
        self._refresh_destination()
        if manifest is None or not self.render_box.isChecked():
            self.frame_label.clear()
            return
        width, height = common_frame(manifest, self._state.config)
        if not (width and height):
            self.frame_label.clear()
            return
        self.frame_label.setText(
            f"Clips exported at one size, {width}x{height}, the smallest clip in the edit"
        )

    def _refresh_destination(self) -> None:
        """Name what this screen writes and where, so the card says where it all lands."""
        out = self._state.output_dir
        manifest = self._state.manifest
        if out is None:
            self.destination_label.clear()
            return
        if manifest is not None and self.render_box.isChecked():
            rendered = render_path(manifest, self._state.config).name
            written = f"{SELECTS_DIR}/ and {rendered}"
        else:
            written = f"{SELECTS_DIR}/"
        self.destination_label.setText(f"{written}, in {short_path(out)}")
        self.destination_label.setToolTip(str(out))

    def _overrides(self) -> ExportOverrides:
        return ExportOverrides(
            fps=None if self.fps_field.value() <= 0 else self.fps_field.value(),
            fast=self.mode_box.currentText() == "fast",
            rejects=self.rejects_box.isChecked(),
        )

    # --- running -----------------------------------------------------------

    def run(self) -> bool:
        state = self._state
        manifest = state.manifest
        if manifest is None or state.is_running:
            return False
        self.apply_options()
        config = state.config
        overrides = self._overrides()
        self.problems.clear()
        self.summary.clear()
        self.bar.setValue(0)

        wanted = self.render_box.isChecked()
        track = resolve_track(manifest)

        def work(progress: ProgressCallback) -> ExportOutcome:
            outcome = ExportOutcome(export_clips(manifest, config, progress, overrides))
            if wanted and not outcome.export.failed:
                # The export has just run, so the render finds its clips current and
                # only joins them.
                outcome.render = render_edit(manifest, config, track=track, progress=progress)
            return outcome

        return state.run_stage("export", work)

    def _on_progress(self, event: object) -> None:
        if not isinstance(event, ProgressEvent):
            return
        if event.stage == "render":
            self.current_label.setText(event.message or "Rendering the montage")
            return
        if event.stage != "export":
            return
        if event.total > 0:
            self.bar.setRange(0, event.total)
            self.bar.setValue(event.current)
        name = Path(event.path).name if event.path else event.message
        self.current_label.setText(f"{event.current} of {event.total}  {name}")

    def _stage_finished(self, name: str) -> None:
        self._set_running(False)
        if name != "export":
            return
        outcome = self._state.last_result
        if isinstance(outcome, ExportOutcome):
            self._result = outcome.export
            self._render = outcome.render
            self.summary.setText(self.describe(outcome.export, outcome.render))
            self.problems.setText(self.describe_problems(outcome.export, outcome.render))
            self.bar.setValue(self.bar.maximum())
            self.current_label.setText("Finished")
        self.refresh_stale()
        self.refresh_render()
        self.exported.emit()

    def _stage_cancelled(self, name: str) -> None:
        self._set_running(False)
        if name == "export":
            self.current_label.setText("Cancelled. The clips already written are in the folder.")

    def describe(self, result: ExportResult, render: RenderResult | None = None) -> str:
        """The run in the numbers a person checks before opening CapCut."""
        manifest = self._state.manifest
        selects = result.selects_dir or (
            Path(manifest.output_dir) / SELECTS_DIR if manifest is not None else None
        )
        size_mb = folder_size(selects) / 1e6 if selects is not None else 0.0
        duration = 0.0
        if manifest is not None:
            duration = sum(
                segment.target_duration_s or 0.0
                for segment in manifest.segments.values()
                if segment.outcome == "selected"
            )
        lines = [
            f"{result.exported} clips written, {result.skipped} unchanged and skipped, "
            f"{result.failed} failed",
            f"{duration:.1f} s of edit, {size_mb:.0f} MB in {selects}",
            f"{result.target_fps:g} fps, {result.slow_motion} slowed down, "
            f"{result.fps_converted} resampled",
        ]
        if result.stale_moved:
            lines.append(f"{result.stale_moved} stale files moved to {STALE_DIR}")
        if render is not None and render.ok and render.path is not None:
            sound = f"with {render.track.name}" if render.track else "silent"
            lines.append(
                f"{render.path.name}: {render.duration_s:.1f} s, "
                f"{render.size_bytes / 1e6:.0f} MB, {render.clips} clips {sound}, hard cuts"
            )
        return "\n".join(lines)

    def describe_problems(self, result: ExportResult, render: RenderResult | None = None) -> str:
        lines = [f"{segment_id}: {error}" for segment_id, error in result.errors]
        lines += list(result.warnings)
        if render is not None:
            lines += [f"render: {error}" for _where, error in render.errors]
        return "\n".join(lines)

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running and self._can_run())
        self.cancel_button.setEnabled(running)
        for widget in (
            self.mode_box,
            self.codec_box,
            self.crf_field,
            self.fps_field,
            self.width_field,
            self.height_field,
            self.vertical_box,
            self.rejects_box,
            self.render_box,
            self.stale_button,
        ):
            widget.setEnabled(not running)
        self.fade_field.setEnabled(not running and self.render_box.isChecked())
        if not running:
            self.refresh_stale()
            self.refresh_render()

    def _can_run(self) -> bool:
        manifest = self._state.manifest
        return manifest is not None and any(
            segment.outcome == "selected" for segment in manifest.segments.values()
        )

    # --- the folder --------------------------------------------------------

    def selects_dir(self) -> Path | None:
        manifest = self._state.manifest
        if manifest is None:
            return None
        return Path(manifest.output_dir) / SELECTS_DIR

    def stale_dir(self) -> Path | None:
        selects = self.selects_dir()
        return selects / STALE_DIR if selects is not None else None

    def stale_files(self) -> list[Path]:
        stale = self.stale_dir()
        if stale is None or not stale.is_dir():
            return []
        return sorted(path for path in stale.iterdir() if path.is_file())

    def stale_preview(self) -> bool:
        """Whether the montage preview describes an edit that no longer exists.

        A montage built from a selection three decisions ago is as stale as a clip file
        from a dropped pick, and it is bigger than all of them put together.
        """
        manifest = self._state.manifest
        if manifest is None or manifest.preview.path is None:
            return False
        track = (
            Path(manifest.soundtrack.audio_path)
            if manifest.soundtrack.audio_path is not None
            else None
        )
        return not is_current(manifest, self._state.config, track)

    def refresh_stale(self) -> None:
        """Say how many stale files are waiting, and offer to remove them."""
        files = self.stale_files()
        preview = self.stale_preview()
        self.stale_button.setEnabled((bool(files) or preview) and not self._state.is_running)
        if files and preview:
            self.stale_button.setText(f"Delete {len(files)} stale files and the old preview")
        elif files:
            self.stale_button.setText(f"Delete {len(files)} stale files")
        elif preview:
            self.stale_button.setText("Delete the old montage preview")
        else:
            self.stale_button.setText("Delete the stale files")

    def delete_stale(self, confirm: bool = True) -> int:
        """Delete what a re-selection left behind. Offered, never automatic.

        Only files directly under ``_selects/_stale/``, plus the montage preview when
        it describes an edit that no longer exists: this is a delete button in a folder
        the user chose, and the narrowest possible reading of what it may remove is the
        only safe one.
        """
        files = self.stale_files()
        preview = self.stale_preview()
        if not files and not preview:
            return 0
        if confirm:
            what = []
            if files:
                what.append(f"{len(files)} files in {STALE_DIR}")
            if preview:
                what.append("the montage preview")
            answer = QMessageBox.question(
                self,
                "Delete the stale files?",
                f"{' and '.join(what)} are from an earlier selection.\nDelete them?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return 0
        removed = 0
        for path in files:
            try:
                path.unlink()
                removed += 1
            except OSError as error:
                self.problems.setText(f"could not delete {path.name}: {error}")
        manifest = self._state.manifest
        if preview and manifest is not None:
            removed += clear_preview(manifest)
            self._state.schedule_save()
        self.refresh_stale()
        return removed

    def render_file(self) -> Path | None:
        """The rendered file for this project, when one is on disk."""
        manifest = self._state.manifest
        if manifest is None:
            return None
        recorded = manifest.render.path
        path = Path(recorded) if recorded else render_path(manifest, self._state.config)
        return path if path.exists() else None

    def refresh_render(self) -> None:
        """Offer the render only when there is one to open."""
        self.render_button.setEnabled(self.render_file() is not None)

    def open_render(self) -> bool:
        """Play the finished file in whatever the system uses for video."""
        path = self.render_file()
        if path is None:
            self.problems.setText("Nothing rendered yet.")
            return False
        from PySide6.QtCore import QUrl

        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))

    def open_folder(self) -> bool:
        """Show the output in the OS file manager, which is where CapCut imports from."""
        selects = self.selects_dir()
        if selects is None or not selects.exists():
            self.problems.setText("Nothing exported yet.")
            return False
        from PySide6.QtCore import QUrl

        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(selects)))
        return bool(opened)


def export_summary(manifest: Manifest, config: AutocutConfig) -> str:
    """The dry run text, without a widget. For tests and for the CLI to reuse later."""
    screen_free = [s for s in manifest.segments.values() if s.outcome == "selected"]
    target = resolve_target_fps(manifest, config)
    total = sum(segment.target_duration_s or 0.0 for segment in screen_free)
    return f"{len(screen_free)} clips, {total:.1f} s, at {target:g} fps"

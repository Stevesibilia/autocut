"""Screen 1: where the footage is, where the edit goes, and how to weigh it.

Everything here is a decision the user makes before any work happens, which is why
it is one screen and not a wizard: adding a second card folder after seeing the file
count is the normal case, not an exception to a flow.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autocut.core.doctor import DoctorReport, inspect_environment
from autocut.core.ingest import ACCEPTED_EXTENSIONS
from autocut.gui.profiles import PROFILES, PROFILES_BY_KEY, apply_profile, diff
from autocut.gui.recent import load_recent, remember
from autocut.gui.state import MANIFEST_NAME, ProjectState
from autocut.gui.widgets.recent import RecentList


def doctor_rows(report: DoctorReport) -> list[tuple[str, str, str]]:
    """The report as status, name and detail, so the table is testable as data."""
    return [(check.marker, check.name, check.detail) for check in report.checks]


def doctor_table(report: DoctorReport) -> str:
    """The report as a small rich text table.

    A table rather than padded text: the details are file paths and sentences of
    different lengths, and a label full of leading spaces wrapped them mid path and
    left the status column ragged. Cells wrap inside their own column instead, and
    the status stays in line down the left. Every value is escaped, because a path
    with an angle bracket in it would otherwise be read as markup.
    """
    rows = "".join(
        f"<tr>"
        f'<td style="padding-right:10px; white-space:nowrap;"><b>{escape(marker)}</b></td>'
        f'<td style="padding-right:8px; white-space:nowrap;">{escape(name)}</td>'
        f"<td>{escape(detail)}</td>"
        f"</tr>"
        for marker, name, detail in doctor_rows(report)
    )
    return f'<table width="100%" cellspacing="0" cellpadding="2">{rows}</table>'


def count_videos(folder: Path) -> int:
    """How many files in ``folder`` the pipeline would accept, counted recursively.

    A count, not a scan: ``ingest`` probes every file with ffprobe, which is seconds
    of work and belongs to the Analysis screen. This is the same extension rule
    without the cost, so the number shown before a run is the number of files the run
    will consider.
    """
    if not folder.is_dir():
        return 0
    return sum(
        1
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in ACCEPTED_EXTENSIONS
    )


class SourceList(QListWidget):
    """The source folders, which can be dropped on as well as browsed for."""

    folders_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._folders: list[Path] = []

    @property
    def folders(self) -> list[Path]:
        return list(self._folders)

    def add_folder(self, folder: Path) -> bool:
        """Add a folder once. False when it is not a directory or already listed."""
        resolved = Path(folder).resolve()
        if not resolved.is_dir() or resolved in self._folders:
            return False
        self._folders.append(resolved)
        count = count_videos(resolved)
        self.addItem(f"{resolved}  ({count} clips)")
        self.folders_changed.emit()
        return True

    def remove_selected(self) -> None:
        for item in self.selectedItems():
            row = self.row(item)
            self.takeItem(row)
            del self._folders[row]
        self.folders_changed.emit()

    def set_folders(self, folders: list[Path]) -> None:
        self.clear()
        self._folders = []
        for folder in folders:
            self.add_folder(folder)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt override
        """Accept folders, and accept a dropped file as the folder holding it.

        Dragging a clip out of a card is how people show you where the footage is,
        and refusing it because it is a file and not a folder teaches nothing.
        """
        added = False
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.exists():
                continue
            added |= self.add_folder(path if path.is_dir() else path.parent)
        if added:
            event.acceptProposedAction()


class ProjectScreen(QWidget):
    """Sources, output folder, profile, the recent list and the doctor report."""

    project_opened = Signal()
    settings_requested = Signal()
    machine_checked = Signal()
    """The doctor report was rebuilt, so the rail can say what this machine can do."""

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("screen-project")
        self._state = state

        self._running = False
        self.sources = SourceList()
        self.sources.folders_changed.connect(self._refresh_counts)
        add_button = self.add_button = QPushButton("Add folder…")
        add_button.clicked.connect(self._browse_source)
        remove_button = self.remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.sources.remove_selected)
        self.count_label = QLabel("No source folders yet")
        self.count_label.setProperty("role", "muted")

        source_box = QGroupBox("Footage")
        source_layout = QVBoxLayout(source_box)
        hint = QLabel("Drop card folders here, or browse for them.")
        hint.setProperty("role", "muted")
        source_layout.addWidget(hint)
        source_layout.addWidget(self.sources, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        source_layout.addLayout(buttons)
        source_layout.addWidget(self.count_label)

        self.output = QLineEdit()
        self.output.setPlaceholderText("Where the clips and manifest.json go")
        self.output.textChanged.connect(self._refresh_output_note)
        output_button = self.output_button = QPushButton("Choose…")
        output_button.clicked.connect(self._browse_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output, 1)
        output_row.addWidget(output_button)

        self.profile = QComboBox()
        for profile in PROFILES:
            self.profile.addItem(profile.title, profile.key)
        self.profile.currentIndexChanged.connect(self._refresh_profile_note)
        self.profile_note = QLabel()
        self.profile_note.setWordWrap(True)
        self.profile_note.setProperty("role", "muted")

        self.output_note = QLabel()
        self.output_note.setWordWrap(True)
        self.output_note.setProperty("role", "muted")

        settings_box = QGroupBox("Edit")
        form = QFormLayout(settings_box)
        form.addRow("Output folder", output_row)
        form.addRow("", self.output_note)
        form.addRow("Profile", self.profile)
        form.addRow("", self.profile_note)

        self.create_button = QPushButton("Create project")
        self.create_button.setProperty("variant", "primary")
        self.create_button.clicked.connect(self.create_project)
        open_button = self.open_button = QPushButton("Open existing…")
        open_button.clicked.connect(self._browse_open)
        settings_button = QPushButton("Settings…")
        settings_button.clicked.connect(self.settings_requested.emit)

        self.recent = RecentList()
        self.recent.opened.connect(self._open_recent)
        self.refresh_recent()
        recent_scroll = QScrollArea()
        recent_scroll.setWidgetResizable(True)
        recent_scroll.setWidget(self.recent)
        recent_box = QGroupBox("Recent projects")
        recent_layout = QVBoxLayout(recent_box)
        recent_layout.addWidget(recent_scroll)

        self.doctor = QLabel()
        self.doctor.setWordWrap(True)
        self.doctor.setTextFormat(Qt.TextFormat.RichText)
        self.doctor.setAlignment(Qt.AlignmentFlag.AlignTop)
        doctor_box = QGroupBox("This machine")
        doctor_layout = QVBoxLayout(doctor_box)
        doctor_layout.addWidget(self.doctor)
        doctor_layout.addStretch(1)
        self.refresh_doctor()

        actions = QHBoxLayout()
        actions.addWidget(self.create_button)
        actions.addWidget(open_button)
        actions.addStretch(1)
        actions.addWidget(settings_button)

        left = QVBoxLayout()
        left.addWidget(source_box, 1)
        left.addWidget(settings_box)
        left.addLayout(actions)

        right = QVBoxLayout()
        right.addWidget(recent_box, 1)
        right.addWidget(doctor_box, 1)

        columns = QWidget()
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.addLayout(left, 3)
        columns_layout.addLayout(right, 2)

        # Scrolled, because the doctor report is as long as the machine is unusual and
        # a screen that cannot scroll hides its own Create project button.
        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QScrollArea.Shape.NoFrame)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setWidget(columns)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(body)

        state.project_changed.connect(self.show_open_project)
        state.stage_started.connect(lambda _name: self._set_running(True))
        state.stage_finished.connect(lambda _name: self._set_running(False))
        state.stage_cancelled.connect(lambda _name: self._set_running(False))

        self._refresh_counts()
        self._refresh_profile_note()

    def _set_running(self, running: bool) -> None:
        """Nothing that changes the project while a stage is running it.

        Opening another project mid analysis would leave the worker writing a manifest
        the window no longer holds, and changing the sources under a run would make the
        summary describe files that are not in the project any more.
        """
        self._running = running
        self.sources.setEnabled(not running)
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running)
        self.output.setEnabled(not running)
        self.output_button.setEnabled(not running)
        self.profile.setEnabled(not running)
        self.open_button.setEnabled(not running)
        self.recent.setEnabled(not running)
        self._refresh_create_enabled()

    def show_open_project(self) -> None:
        """Put the state's project on this screen, whoever opened it.

        A project can be opened from the command line (``autocut gui <folder>``) or
        from the recent list, and this screen has to show the same project the rest of
        the window is working on rather than whatever was last typed into it.
        """
        state = self._state
        if state.manifest is None or state.output_dir is None:
            return
        if self.sources.folders != [Path(source).resolve() for source in state.manifest.sources]:
            self.sources.set_folders(list(state.manifest.sources))
        if self.output.text() != str(state.output_dir):
            self.output.setText(str(state.output_dir))
        self.refresh_doctor()

    # --- browsing -----------------------------------------------------------

    def _browse_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a footage folder")
        if folder:
            self.sources.add_folder(Path(folder))

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose the output folder")
        if folder:
            self.output.setText(folder)

    def _browse_open(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open a project folder")
        if folder:
            self.open_project(Path(folder))

    # --- the labels that react ---------------------------------------------

    def _refresh_counts(self) -> None:
        folders = self.sources.folders
        if not folders:
            self.count_label.setText("No source folders yet")
        else:
            total = sum(count_videos(folder) for folder in folders)
            self.count_label.setText(
                f"{total} clips across {len(folders)} folder{'s' if len(folders) > 1 else ''}"
            )
        self._refresh_create_enabled()

    def _refresh_output_note(self) -> None:
        """Say when the chosen folder already holds a project, before anything is done."""
        text = self.output.text().strip()
        path = Path(text) if text else None
        if path is not None and (path / MANIFEST_NAME).exists():
            self.output_note.setText(
                f"{MANIFEST_NAME} is already in this folder. Creating the project will "
                "continue that analysis rather than start again."
            )
            self.create_button.setText("Continue project")
        else:
            self.output_note.clear()
            self.create_button.setText("Create project")
        self._refresh_create_enabled()

    def _refresh_create_enabled(self) -> None:
        has_sources = bool(self.sources.folders)
        has_output = bool(self.output.text().strip())
        self.create_button.setEnabled(has_sources and has_output and not self._running)

    def _refresh_profile_note(self) -> None:
        profile = PROFILES_BY_KEY[str(self.profile.currentData())]
        changes = diff(self._state.config, profile)
        if not changes:
            self.profile_note.setText(profile.summary)
            return
        listed = "\n".join(f"  {change.line}" for change in changes)
        self.profile_note.setText(f"{profile.summary}\n\nIt will change:\n{listed}")

    def refresh_doctor(self) -> None:
        """The doctor report, so a missing ffmpeg is seen before a run, not during one."""
        self.doctor_report = inspect_environment(self._state.config)
        self.doctor.setText(doctor_table(self.doctor_report))
        self.machine_checked.emit()

    def refresh_recent(self) -> None:
        self.recent.set_projects(load_recent())

    # --- the two things this screen actually does --------------------------

    def create_project(self) -> bool:
        """Apply the profile, open or create the project in the output folder."""
        text = self.output.text().strip()
        if not text or not self.sources.folders:
            return False
        if self._refuse_while_running():
            return False
        out = Path(text)
        profile = PROFILES_BY_KEY[str(self.profile.currentData())]
        try:
            self._state.new_project(self.sources.folders, out)
        except OSError as error:
            QMessageBox.warning(self, "Cannot use that folder", str(error))
            return False
        apply_profile(self._state.config, profile)
        self._state.refresh_config_snapshot()
        remember(out)
        self.refresh_recent()
        self.refresh_doctor()
        self.project_opened.emit()
        return True

    def _refuse_while_running(self) -> bool:
        """True when a stage is running, having said so. Belt and braces to the disabling.

        The buttons are disabled during a run, but both methods are public and are
        called directly by tests and by the window, so the refusal is checked here as
        well as shown in the widgets.
        """
        if not self._state.is_running:
            return False
        QMessageBox.warning(
            self,
            "A stage is running",
            "Wait for the analysis to finish or cancel it before changing the project.",
        )
        return True

    def open_project(self, folder: Path) -> bool:
        """Open an analyzed project and put its sources back on this screen."""
        if self._refuse_while_running():
            return False
        try:
            self._state.open_project(folder)
        except (FileNotFoundError, ValueError) as error:
            QMessageBox.warning(self, "Cannot open that project", str(error))
            return False
        remember(folder)
        self.refresh_recent()
        self.refresh_doctor()
        self.project_opened.emit()
        return True

    def _open_recent(self, folder: str) -> None:
        if folder:
            self.open_project(Path(folder))

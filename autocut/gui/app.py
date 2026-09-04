"""The window, its navigation, and the entry point ``autocut gui`` calls.

Five screens in the order the work happens, and a screen is reachable when the
project has what it needs: there is nothing to review before an analysis and nothing
to export before a selection. The rules live here rather than in the screens so that
one place decides what is possible, and so a screen never has to guess whether it
should be showing an empty state or a real one.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from autocut.core.manifest import Manifest
from autocut.gui.screens.analysis import AnalysisScreen
from autocut.gui.screens.placeholder import PlaceholderScreen
from autocut.gui.screens.project import ProjectScreen
from autocut.gui.screens.review import ReviewScreen
from autocut.gui.settings import SettingsDialog
from autocut.gui.state import ProjectState

APP_TITLE = "AutoCut"


@dataclass(frozen=True, slots=True)
class ScreenSpec:
    """One navigation entry: its label and what a project needs to reach it."""

    key: str
    title: str
    needs: str  # "nothing", "project", "segments" or "selection"


SCREENS: tuple[ScreenSpec, ...] = (
    ScreenSpec("project", "Project", "nothing"),
    ScreenSpec("analysis", "Analysis", "project"),
    ScreenSpec("review", "Review", "segments"),
    ScreenSpec("soundtrack", "Soundtrack", "selection"),
    ScreenSpec("export", "Export", "selection"),
)


def screen_available(spec: ScreenSpec, manifest: Manifest | None) -> bool:
    """Whether ``spec`` can be opened for this manifest.

    Kept a function of the manifest alone so it is testable without a window, which
    is the whole reason the rules are not scattered through the screens.
    """
    if spec.needs == "nothing":
        return True
    if manifest is None:
        return False
    if spec.needs == "project":
        return True
    if spec.needs == "segments":
        return bool(manifest.segments)
    return any(segment.outcome == "selected" for segment in manifest.segments.values())


class MainWindow(QMainWindow):
    """The one window. Navigation on the left, the current screen filling the rest."""

    def __init__(self, state: ProjectState | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 760)
        self.state = state or ProjectState(self)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(180)
        self.nav.setFrameShape(QListWidget.Shape.NoFrame)
        for spec in SCREENS:
            self.nav.addItem(QListWidgetItem(spec.title))
        self.nav.currentRowChanged.connect(self._show_row)

        self.stack = QStackedWidget()
        self.screens: dict[str, QWidget] = {
            "project": ProjectScreen(self.state),
            "analysis": AnalysisScreen(self.state),
            "review": ReviewScreen(self.state),
            "soundtrack": PlaceholderScreen(
                "Soundtrack",
                "The prompt, its variants and the beat sync arrive with m5-gui-soundtrack-export.",
            ),
            "export": PlaceholderScreen(
                "Export",
                "The export queue and the CapCut hand off arrive with m5-gui-soundtrack-export.",
            ),
        }
        for spec in SCREENS:
            self.stack.addWidget(self.screens[spec.key])

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self._status = QLabel("No project open")
        self.statusBar().addWidget(self._status)

        project_screen = self.screens["project"]
        assert isinstance(project_screen, ProjectScreen)
        project_screen.project_opened.connect(self._project_opened)
        project_screen.settings_requested.connect(self.open_settings)

        self.state.segments_changed.connect(lambda _ids: self.refresh_navigation())
        self.state.selection_changed.connect(self.refresh_navigation)
        self.state.error.connect(self._show_error)
        self.state.saved.connect(lambda: self._set_status("Saved"))
        self.state.stage_started.connect(lambda name: self._set_status(f"Running {name}"))
        self.state.stage_finished.connect(lambda name: self._set_status(f"{name} finished"))
        self.state.stage_cancelled.connect(lambda name: self._set_status(f"{name} cancelled"))

        self.nav.setCurrentRow(0)
        self.refresh_navigation()
        apply_theme(QApplication.instance())

    # --- navigation ---------------------------------------------------------

    def refresh_navigation(self) -> None:
        """Enable the screens this project has earned, and title the window after it."""
        manifest = self.state.manifest
        for row, spec in enumerate(SCREENS):
            item = self.nav.item(row)
            available = screen_available(spec, manifest)
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsEnabled
                if available
                else item.flags() & ~Qt.ItemFlag.ItemIsEnabled
            )
        if self.state.output_dir is not None:
            self.setWindowTitle(f"{APP_TITLE} — {self.state.output_dir.name}")
        else:
            self.setWindowTitle(APP_TITLE)

    def go_to(self, key: str) -> None:
        for row, spec in enumerate(SCREENS):
            if spec.key == key:
                self.nav.setCurrentRow(row)
                return

    def _show_row(self, row: int) -> None:
        if 0 <= row < len(SCREENS):
            self.stack.setCurrentWidget(self.screens[SCREENS[row].key])

    # --- reacting to the state ---------------------------------------------

    def _project_opened(self) -> None:
        self.refresh_navigation()
        self.go_to("analysis")
        self._set_status(f"Opened {self.state.output_dir}")

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "AutoCut", message)
        self._set_status(message)

    def open_settings(self) -> None:
        SettingsDialog(self.state, self).exec()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        """Never lose review work, and never leave a thread running behind the window."""
        if self.state.is_running:
            self.state.cancel()
            self.state.wait_for_stage(10_000)
        self.state.close_project()
        event.accept()


def apply_theme(app: object) -> None:
    """Follow the OS. Fusion on Linux, the platform style everywhere else.

    macOS has a native style that already tracks light and dark, so touching it there
    would only make AutoCut look less like a Mac application. Linux has no single
    answer, and Fusion at least reads the desktop palette instead of inventing one.
    """
    if not isinstance(app, QApplication):
        return
    if sys.platform.startswith("linux"):
        app.setStyle("Fusion")
    palette = app.palette()
    dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
    app.setProperty("autocut_dark", dark)


def run(project: Path | None = None) -> int:
    """Start the application. Returns the exit code, so ``autocut gui`` can pass it on."""
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    window = MainWindow()
    if project is not None:
        try:
            window.state.open_project(project)
        except (FileNotFoundError, ValueError) as error:
            QMessageBox.warning(window, "AutoCut", str(error))
        else:
            window.refresh_navigation()
            window.go_to("analysis")
    window.show()
    return int(app.exec())


def build_window(state: ProjectState | None = None) -> MainWindow:
    """A window without starting an event loop, for tests and for screenshots."""
    return MainWindow(state)

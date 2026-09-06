"""The window, its navigation, and the entry point ``autocut gui`` calls.

Five screens in the order the work happens, and a screen is reachable when the
project has what it needs: there is nothing to review before an analysis and nothing
to export before a selection. The rules live here rather than in the screens so that
one place decides what is possible, and so a screen never has to guess whether it
should be showing an empty state or a real one.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QCloseEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from autocut.core.config import AutocutConfig, GuiConfig
from autocut.core.doctor import DoctorReport
from autocut.core.manifest import Manifest
from autocut.gui import theme
from autocut.gui.layout import load_layout, save_layout
from autocut.gui.screens.analysis import AnalysisScreen
from autocut.gui.screens.export import ExportScreen
from autocut.gui.screens.project import ProjectScreen
from autocut.gui.screens.review import ReviewScreen
from autocut.gui.screens.soundtrack import SoundtrackScreen
from autocut.gui.settings import SettingsDialog
from autocut.gui.state import CONFIG_NAME, ProjectState
from autocut.gui.theme import icons
from autocut.gui.widgets.rail import NavRail
from autocut.gui.widgets.topbar import Counter, TopBar

APP_TITLE = "AutoCut"

#: Dragging a splitter emits on every pixel; the layout file is not worth that.
LAYOUT_SAVE_DEBOUNCE_MS = 400


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


@runtime_checkable
class BarScreen(Protocol):
    """A screen that fills the top bar with its own counters and actions.

    Not called `actions` because `QWidget.actions` already means something in Qt and
    shadowing it would quietly break every context menu.
    """

    def bar_counters(self) -> list[Counter]: ...

    def bar_actions(self) -> list[QWidget]: ...


#: What the window opens at when the screen is big enough to hold it. The design size
#: of the approved mockup.
DESIGN_SIZE = QSize(1440, 900)


def available_size() -> QSize:
    """The usable area of the primary screen, or the design size when there is none.

    Offscreen there is a virtual screen with a geometry of its own, which is why the
    test for this monkeypatches it rather than trusting whatever the platform invents.
    """
    screen = QApplication.primaryScreen()
    if screen is None:
        return DESIGN_SIZE
    available = screen.availableGeometry()
    return QSize(available.width(), available.height())


def opening_size(gui: GuiConfig, available: QSize | None = None) -> QSize:
    """The size to open at: the design size, or the screen when the screen is smaller.

    Never under the configured minimum, because a window that opens smaller than it can
    be dragged to is a window Qt immediately grows again.
    """
    room = available if available is not None else available_size()
    return QSize(
        max(min(DESIGN_SIZE.width(), room.width()), gui.min_window_width),
        max(min(DESIGN_SIZE.height(), room.height()), gui.min_window_height),
    )


class MainWindow(QMainWindow):
    """The one window. Navigation on the left, the current screen filling the rest."""

    def __init__(self, state: ProjectState | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.state = state or ProjectState(self)
        # Before anything is built. The rail renders its icons and the few inline colours
        # it needs from the active theme at construction, so a window built first and
        # dressed afterwards keeps the previous theme's rail on a repainted background.
        apply_theme(QApplication.instance(), self.state.config.gui.theme)

        self.rail = NavRail(tuple((spec.key, spec.title) for spec in SCREENS))
        self.rail.screen_chosen.connect(self.go_to)

        self.top_bar = TopBar()

        self.stack = QStackedWidget()
        self.stack.currentChanged.connect(lambda _index: self.refresh_top_bar())
        self.screens: dict[str, QWidget] = {
            "project": ProjectScreen(self.state),
            "analysis": AnalysisScreen(self.state),
            "review": ReviewScreen(self.state),
            "soundtrack": SoundtrackScreen(self.state),
            "export": ExportScreen(self.state),
        }
        for spec in SCREENS:
            self.stack.addWidget(self.screens[spec.key])

        main_column = QVBoxLayout()
        main_column.setContentsMargins(0, 0, 0, 0)
        main_column.setSpacing(0)
        main_column.addWidget(self.top_bar)
        main_column.addWidget(self.stack, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.rail)
        layout.addLayout(main_column, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self._status = QLabel("No project open")
        self.statusBar().addWidget(self._status)

        project_screen = self.screens["project"]
        assert isinstance(project_screen, ProjectScreen)
        project_screen.project_opened.connect(self._project_opened)
        project_screen.settings_requested.connect(self.open_settings)
        project_screen.machine_checked.connect(self._machine_checked)

        review_screen = self.screens["review"]
        assert isinstance(review_screen, ReviewScreen)
        for key in ("review", "analysis"):
            screen = self.screens[key]
            assert isinstance(screen, ReviewScreen | AnalysisScreen)
            screen.open_project_requested.connect(lambda: self.go_to("project"))

        self.state.segments_changed.connect(lambda _ids: self.refresh_navigation())
        self.state.selection_changed.connect(self.refresh_navigation)
        self.state.error.connect(self._show_error)
        self.state.saved.connect(lambda: self._set_status("Saved"))
        self.state.stage_started.connect(lambda name: self._set_status(f"Running {name}"))
        self.state.stage_finished.connect(lambda name: self._set_status(f"{name} finished"))
        self.state.stage_cancelled.connect(lambda name: self._set_status(f"{name} cancelled"))

        self.state.segments_changed.connect(lambda _ids: self.refresh_top_bar())
        self.state.selection_changed.connect(self.refresh_top_bar)

        # How the user arranged the window, per machine. Saved through a short debounce
        # because dragging a splitter emits on every pixel and this is a file on disk.
        self.layout_state = load_layout()
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(LAYOUT_SAVE_DEBOUNCE_MS)
        self._layout_timer.timeout.connect(self._save_layout)
        self.rail.collapsed_changed.connect(lambda _on: self._layout_changed())
        review_screen.split_changed.connect(self._layout_changed)

        # After the widgets exist, so the layouts have reported what they need before
        # the floor is imposed on them. The floor is a promise the layout has to be able
        # to keep; a test asserts the minimum size hint of every screen fits inside it.
        gui = self.state.config.gui
        self.setMinimumSize(gui.min_window_width, gui.min_window_height)
        opening = opening_size(gui)
        self.resize(opening)

        self.rail.set_collapsed(self.layout_state.rail_collapsed)
        if self.layout_state.review_panel_visible is not None:
            self.state.review_panel_visible = self.layout_state.review_panel_visible
        review_screen.adopt_panel_state(opening.width())
        if self.layout_state.review_split:
            review_screen.set_split(self.layout_state.review_split)
        else:
            review_screen.apply_default_split()

        self.go_to("project")
        self.refresh_navigation()

    # --- navigation ---------------------------------------------------------

    def refresh_navigation(self) -> None:
        """Enable the screens this project has earned, and title the window after it."""
        manifest = self.state.manifest
        for spec in SCREENS:
            self.rail.set_available(spec.key, screen_available(spec, manifest))
        self.rail.set_machine(self.doctor_report, self.state.config.providers.cloud)
        if self.state.output_dir is not None:
            self.setWindowTitle(f"{APP_TITLE} — {self.state.output_dir.name}")
        else:
            self.setWindowTitle(APP_TITLE)
        self.refresh_top_bar()

    def go_to(self, key: str) -> None:
        """Show a screen and mark it in the rail.

        Deliberately not guarded by `screen_available`: the rail disables what the
        project has not earned, and the window itself sends the user to a screen after
        an open or a stage, where refusing would leave them looking at the wrong one.
        """
        if key not in self.screens:
            return
        self.stack.setCurrentWidget(self.screens[key])
        self.rail.set_current(key)

    def _layout_changed(self) -> None:
        """Something moved. Write it soon, not now."""
        self._layout_timer.start()

    def _save_layout(self) -> None:
        review = self.screens["review"]
        assert isinstance(review, ReviewScreen)
        self.layout_state.rail_collapsed = self.rail.collapsed
        self.layout_state.review_split = review.split()
        self.layout_state.review_panel_visible = self.state.review_panel_visible
        save_layout(self.layout_state)

    @property
    def doctor_report(self) -> DoctorReport | None:
        """What the Project screen last found out about this machine.

        The probe runs there because that is the screen that shows it in full; the rail
        borrows the answer rather than running ffmpeg a second time.
        """
        screen = self.screens["project"]
        assert isinstance(screen, ProjectScreen)
        return getattr(screen, "doctor_report", None)

    def _machine_checked(self) -> None:
        self.rail.set_machine(self.doctor_report, self.state.config.providers.cloud)

    @property
    def current_key(self) -> str:
        """The key of the screen on show."""
        current = self.stack.currentWidget()
        return next((key for key, screen in self.screens.items() if screen is current), "")

    def refresh_top_bar(self) -> None:
        """Fill the bar from the project and from whichever screen is on show."""
        manifest = self.state.manifest
        if manifest is None:
            self.top_bar.clear_project()
            return
        name = self.state.output_dir.name if self.state.output_dir else APP_TITLE
        self.top_bar.set_project(name, len(manifest.files), len(manifest.segments))
        screen = self.stack.currentWidget()
        if isinstance(screen, BarScreen):
            self.top_bar.set_counters(screen.bar_counters())
            self.top_bar.set_actions(screen.bar_actions())
        else:
            self.top_bar.set_counters([])
            self.top_bar.set_actions([])

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
        # Written now rather than on the debounce: the timer will not fire once the
        # window is gone, and the arrangement the user left is the one to restore.
        self._save_layout()
        if self.state.is_running:
            self.state.cancel()
            self.state.wait_for_stage(10_000)
        self.state.close_project()
        event.accept()


def resolve_theme(setting: str, app: QApplication) -> theme.ThemeName:
    """Which token set `setting` means on this desktop right now.

    `system` is a setting rather than a theme, so it is answered here, once, from the
    palette the platform hands the application before anything is styled. Everything
    downstream sees `dark` or `light` and nothing else.
    """
    if setting in ("dark", "light"):
        return cast("theme.ThemeName", setting)
    window = app.palette().color(QPalette.ColorRole.Window)
    return "dark" if window.lightness() < 128 else "light"


def theme_palette(tokens: theme.Palette) -> QPalette:
    """A `QPalette` carrying the token colours.

    The stylesheet covers the widgets the window uses, but Qt paints a few things from
    the palette whatever the stylesheet says: the text cursor, a drag highlight, the
    frame a native dialog draws. Building the palette from the same tokens means those
    match instead of arriving in the desktop's colours.
    """
    palette = QPalette()
    background = theme.qcolor(tokens.background)
    surface = theme.qcolor(tokens.surface)
    text = theme.qcolor(tokens.text)
    muted = theme.qcolor(tokens.text_muted)
    accent = theme.qcolor(tokens.accent)

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Window, background)
        palette.setColor(group, QPalette.ColorRole.Base, surface)
        palette.setColor(group, QPalette.ColorRole.AlternateBase, theme.qcolor(tokens.rail))
        palette.setColor(group, QPalette.ColorRole.Button, surface)
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, theme.qcolor(tokens.surface_raised))
        palette.setColor(group, QPalette.ColorRole.WindowText, text)
        palette.setColor(group, QPalette.ColorRole.Text, text)
        palette.setColor(group, QPalette.ColorRole.ButtonText, text)
        palette.setColor(group, QPalette.ColorRole.ToolTipText, text)
        palette.setColor(group, QPalette.ColorRole.BrightText, theme.qcolor(tokens.amber))
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, muted)
        palette.setColor(group, QPalette.ColorRole.Link, accent)
        palette.setColor(group, QPalette.ColorRole.LinkVisited, accent)
        palette.setColor(group, QPalette.ColorRole.Highlight, theme.qcolor(tokens.accent_surface))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, accent)
        palette.setColor(group, QPalette.ColorRole.Mid, theme.qcolor(tokens.border))
        palette.setColor(group, QPalette.ColorRole.Dark, theme.qcolor(tokens.border_strong))

    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.HighlightedText,
    ):
        palette.setColor(disabled, role, muted)
    palette.setColor(disabled, QPalette.ColorRole.Window, background)
    palette.setColor(disabled, QPalette.ColorRole.Base, surface)
    palette.setColor(disabled, QPalette.ColorRole.Button, surface)
    palette.setColor(disabled, QPalette.ColorRole.Highlight, theme.qcolor(tokens.surface_raised))
    return palette


def apply_theme(app: object, setting: str = "dark") -> theme.Theme:
    """Dress the application: Fusion, the token palette, the bundled fonts, the sheet.

    Fusion on every platform, which is the decision ADR 10 records: the native macOS
    style paints its own controls and ignores most of a stylesheet, so it is the one
    style a design system cannot be applied on top of. Everything the window looks
    like is decided here and in `autocut/gui/theme`.
    """
    if not isinstance(app, QApplication):
        return theme.current()
    app.setStyle("Fusion")
    active = theme.activate(resolve_theme(setting, app))
    theme.register()
    icons.clear_cache()
    app.setPalette(theme_palette(active.palette))
    app.setFont(theme.font(active.metrics.body_size))
    app.setStyleSheet(theme.stylesheet(active))
    # Read by the screenshot test and by anything that has to know which way round the
    # window is without importing the theme.
    app.setProperty("autocut_theme", active.name)
    app.setProperty("autocut_dark", active.name == "dark")
    # Recorded because `app.style()` answers to no name while a stylesheet is installed:
    # Qt wraps the real style in a proxy, and the proxy has none.
    app.setProperty("autocut_style", "Fusion")
    return active


def theme_setting(project: Path | None) -> str:
    """The theme this start should use, read from the project being opened if there is one.

    The window is dressed before it is built, so the configuration has to be read here
    rather than waiting for the project to open: a light project that flashed dark for
    a frame would be worse than one that never changed at all.
    """
    if project is None:
        return AutocutConfig().gui.theme
    directory = project if project.is_dir() else project.parent
    return AutocutConfig.load(directory / CONFIG_NAME).gui.theme


def configure_logging(verbose: bool = False) -> None:
    """Send the window's own log lines to the terminal it was started from.

    Nothing in this project configured logging, so every `logger.info` and
    `logger.debug` went to a root logger with no handler and printed nothing. The
    macOS reports that said "nothing appeared on Stop" were reading an empty stream,
    not a slot that never ran, and the diagnostics added for those reports were
    invisible on the machine that needed them.

    Warnings still reach the terminal without this, through Python's last resort
    handler, which is why the playback failures did show up.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("autocut").setLevel(level)


def diagnose(project: Path | None = None) -> int:
    """Print what the window sees, and exit without entering the event loop.

    Every defect the macOS runs found was seen by eye and reported in prose: an icon
    that "looks like a corner", a panel "cut off at the edge". This exists so the next
    one arrives as numbers, from the machine that has the problem.
    """
    configure_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    setting = theme_setting(project)
    active = apply_theme(app, setting)
    families = theme.families()

    lines = [f"AutoCut {version('autocut')} diagnostics", ""]
    primary = app.primaryScreen()
    for screen in app.screens():
        geometry = screen.geometry()
        usable = screen.availableGeometry()
        mark = " (primary)" if screen is primary else ""
        lines.append(
            f"screen {screen.name() or '?'}{mark}: "
            f"geometry {geometry.width()}x{geometry.height()}, "
            f"available {usable.width()}x{usable.height()}, "
            f"device pixel ratio {screen.devicePixelRatio():g}, "
            f"logical dpi {screen.logicalDotsPerInch():g}"
        )
    if not app.screens():
        lines.append("screens: none reported by this platform")

    lines += [
        "",
        f"platform: {sys.platform}, Qt platform plugin {app.platformName()}",
        f"font text: {families.text}",
        f"font mono: {families.mono}",
        f"fonts bundled: {'yes' if families.bundled else 'no, fell back to the platform'}",
        f"application font: {app.font().family()} at {app.font().pixelSize()} px",
        f"theme setting: {setting}",
        f"theme resolved: {active.name}",
        f"style: {app.property('autocut_style') or 'unknown'}",
        "",
    ]

    window = MainWindow()
    hint = window.minimumSizeHint()
    minimum = window.minimumSize()
    room = available_size()
    lines += [
        f"window minimum size hint: {hint.width()}x{hint.height()}",
        f"window minimum size: {minimum.width()}x{minimum.height()}",
        f"window opening size: {window.width()}x{window.height()}",
        f"screen available for opening: {room.width()}x{room.height()}",
    ]
    if window.width() > room.width() or window.height() > room.height():
        lines.append(
            "  note: the opening size is larger than the screen because the configured "
            "minimum wins over it. gui.min_window_width and gui.min_window_height are "
            "what to lower if this machine cannot hold the window."
        )
    for spec in SCREENS:
        window.go_to(spec.key)
        screen_hint = window.minimumSizeHint()
        lines.append(
            f"  showing {spec.key}: minimum size hint {screen_hint.width()}x{screen_hint.height()}"
        )

    print("\n".join(lines))
    window.close()
    return 0


def run(project: Path | None = None, verbose: bool = False) -> int:
    """Start the application. Returns the exit code, so ``autocut gui`` can pass it on."""
    configure_logging(verbose)
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    apply_theme(app, theme_setting(project))
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

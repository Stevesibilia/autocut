"""The navigation rail: the five screens, and what this machine can do.

A rail of icons and labels rather than the list widget the first version used, because
a list paints the desktop's selection and a rail can say which screen is current in the
accent colour and which are still out of reach. The machine block at the bottom answers
the question that used to need a trip to the Project screen: whether ffmpeg is there,
what will run the embeddings and whether anything is going to the cloud.

The rail knows nothing about the screens beyond their keys. It reports a click and the
window decides what that means, which is where the rules about what is reachable live.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from autocut.core.doctor import DoctorReport
from autocut.gui import theme
from autocut.gui.theme import icons

#: The icon each screen is drawn with, by the key the window knows it as.
SCREEN_ICONS: dict[str, str] = {
    "project": "folder",
    "analysis": "activity",
    "review": "square-play",
    "soundtrack": "music",
    "export": "download",
}

ICON_SIZE = 16
LOGO_SIZE = 28


@dataclass(frozen=True, slots=True)
class MachineLine:
    """One line of the machine block: a word, and whether it is a working one."""

    text: str
    ok: bool


def machine_lines(report: DoctorReport | None, cloud_enabled: bool = True) -> list[MachineLine]:
    """The three things worth knowing about this machine, from the doctor report.

    Short on purpose: the rail has room for a few words each, so the ffmpeg check keeps
    its version and loses the path it was found at. The full report is still on the
    Project screen for when a few words are not enough.

    Cloud takes the configuration as well as the report, because a stored key with
    `providers.cloud` off means nothing is going anywhere and the rail should say so.
    """
    if report is None:
        return [MachineLine("checking the machine", False)]

    ffmpeg = report.ffmpeg
    version = ffmpeg.detail.split(" at ", 1)[0] if ffmpeg.ok else ""
    embeddings = (
        f"CLIP on {report.compute_device.detail.upper()}"
        if report.ai_extra.ok
        else "no embeddings, the ai extra is missing"
    )
    cloud = report.cloud_key.ok and cloud_enabled
    return [
        MachineLine(f"ffmpeg {version}" if ffmpeg.ok else "ffmpeg is missing", ffmpeg.ok),
        MachineLine(embeddings, report.ai_extra.ok),
        MachineLine("cloud on" if cloud else "cloud off", cloud),
    ]


class _Dot(QWidget):
    """A six pixel status dot, filled from the tokens."""

    def __init__(self, ok: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(6, 6)
        colors = theme.current().palette
        colour = colors.accent if ok else colors.border_muted
        self.setStyleSheet(f"background: {colour}; border-radius: 3px;")


class NavRail(QWidget):
    """The rail itself: a mark, five screens, and the machine block."""

    screen_chosen = Signal(str)
    """The key of the screen the user clicked."""

    def __init__(self, screens: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        metrics = theme.current().metrics
        colors = theme.current().palette
        self.setFixedWidth(metrics.rail_width)

        column = QVBoxLayout(self)
        column.setContentsMargins(12, 20, 12, 20)
        column.setSpacing(4)
        column.addWidget(self._brand(colors, metrics))
        column.addSpacing(metrics.space * 2)

        self.buttons: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, title in screens:
            button = self._rail_button(key, title, colors)
            self.buttons[key] = button
            self._group.addButton(button)
            column.addWidget(button)

        column.addStretch(1)
        self.machine = QWidget()
        self.machine.setObjectName("machineBlock")
        self.machine.setStyleSheet(
            f"QWidget#machineBlock {{ background: {colors.surface};"
            f" border-radius: {metrics.radius_control}px; }}"
        )
        self._machine_layout = QVBoxLayout(self.machine)
        self._machine_layout.setContentsMargins(10, 10, 10, 10)
        self._machine_layout.setSpacing(6)
        column.addWidget(self.machine)
        self.set_machine(None)

    # --- building ----------------------------------------------------------

    def _brand(self, colors: theme.Palette, metrics: theme.Metrics) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(10, 6, 10, 0)
        row.setSpacing(10)

        mark = QLabel()
        mark.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(
            f"background: {colors.accent}; border-radius: {metrics.radius_control}px;"
        )
        mark.setPixmap(icons.pixmap("film", colors.on_accent, ICON_SIZE, self._ratio()))

        name = QLabel("AutoCut")
        name.setProperty("role", "title")
        row.addWidget(mark)
        row.addWidget(name)
        row.addStretch(1)
        return holder

    def _rail_button(self, key: str, title: str, colors: theme.Palette) -> QToolButton:
        button = QToolButton()
        button.setText(title)
        button.setProperty("rail", True)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setIcon(
            theme.two_state_icon(
                SCREEN_ICONS[key], colors.text_muted, colors.accent, ICON_SIZE, self._ratio()
            )
        )
        button.clicked.connect(lambda _checked, name=key: self.screen_chosen.emit(name))
        return button

    def _ratio(self) -> float:
        return float(self.devicePixelRatioF() or 1.0)

    # --- state -------------------------------------------------------------

    def set_current(self, key: str) -> None:
        """Mark `key` as the screen on show, without emitting anything."""
        button = self.buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_available(self, key: str, available: bool) -> None:
        """A screen the project has not earned yet is visible but not clickable."""
        button = self.buttons.get(key)
        if button is not None:
            button.setEnabled(available)

    def set_machine(self, report: DoctorReport | None, cloud_enabled: bool = True) -> None:
        """Redraw the machine block from a doctor report, or say it is being checked."""
        while self._machine_layout.count():
            item = self._machine_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                # Unparent before deleting: deleteLater only takes effect when the
                # event loop next runs, and until then the old label is still a child
                # and still findable, which made a rebuilt block read as two blocks.
                widget.setParent(None)
                widget.deleteLater()

        heading = QLabel("This machine")
        heading.setProperty("role", "label")
        self._machine_layout.addWidget(heading)
        for line in machine_lines(report, cloud_enabled):
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            layout.addWidget(_Dot(line.ok), 0, Qt.AlignmentFlag.AlignVCenter)
            label = QLabel(line.text)
            if not line.ok:
                label.setProperty("role", "muted")
            label.setWordWrap(True)
            layout.addWidget(label, 1)
            self._machine_layout.addWidget(row)

"""The bar over every screen: what this project is, and what the screen can do.

The counters used to live in the Review screen's header, where they were invisible from
every other screen and where two screens counting the same edit would have had to agree
by hand. They belong to the project, so they belong to the window.

The bar owns none of the behaviour. A screen hands it a line of counters and a row of
its own buttons through `set_counters` and `set_actions`, and the window swaps them when
the screen changes; the buttons stay the screen's, connected to the screen's slots.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from autocut.gui import theme


def _effective_width(widget: QWidget) -> int:
    """The width a layout will actually give `widget`.

    Not `sizeHint().width()`: `setFixedWidth` moves the minimum and the maximum and
    leaves the hint alone, so a button pinned to 220 px still hints at 83 and every
    measurement built on the hint is wrong by the difference.
    """
    hint = widget.sizeHint().width()
    return min(max(hint, widget.minimumWidth()), widget.maximumWidth())


def _action_label(action: QWidget) -> str:
    """What to call an action in the overflow menu."""
    text = getattr(action, "text", None)
    label = text() if callable(text) else ""
    return str(label) or action.toolTip() or action.objectName() or "Action"


def _clicker(action: QWidget) -> Callable[[], None]:
    """Press the real button, so the menu entry and the button do the same thing."""

    def press() -> None:
        click = getattr(action, "click", None)
        if callable(click):
            click()

    return press


#: The project block never disappears and never takes the bar over. Wide enough for a
#: recognisable folder name, narrow enough that the counters and actions keep their room.
IDENTITY_MIN_WIDTH = 140
IDENTITY_MAX_WIDTH = 320


#: The upright rule between the project name and the counters, tall enough to read as
#: a divider between two blocks of text rather than as a stray mark.
DIVIDER_HEIGHT = 28


def duration_label(seconds: float) -> str:
    """`m:ss`, the way an edit length is written everywhere in the window."""
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"


@dataclass(frozen=True, slots=True)
class Counter:
    """One number and the word under it. The number is drawn in the mono face."""

    value: str
    label: str
    #: The one counter a screen wants read first, drawn in the accent colour.
    accent: bool = False


def edit_counters(
    clips: int,
    duration_s: float,
    bpm: int | None,
    kept: int,
    rejected: int,
) -> list[Counter]:
    """The four counters the Review screen puts in the bar.

    A pure function so the numbers can be tested without a window, and so the same
    wording is used wherever an edit is counted.
    """
    return [
        Counter(str(clips), "clips", accent=True),
        Counter(duration_label(duration_s), "edit"),
        Counter(str(bpm) if bpm else "not synced", "bpm synced"),
        Counter(f"{kept} · {rejected}", "kept · rejected"),
    ]


class TopBar(QWidget):
    """Project name and counts on the left, the current screen's actions on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        metrics = theme.current().metrics
        self.setFixedHeight(metrics.top_bar_height)

        row = QHBoxLayout(self)
        row.setContentsMargins(metrics.space * 3, 0, metrics.space * 3, 0)
        row.setSpacing(metrics.space * 3)

        # Elided rather than shrunk to nothing: the labels must not demand their full
        # width, or a long project name alone stops the window getting smaller, but a
        # name that vanishes is worse than one cut short.
        self.title = QLabel("No project open")
        self.title.setProperty("role", "heading")
        self.subtitle = QLabel("")
        self.subtitle.setProperty("role", "muted")
        self._identity_text = ("No project open", "")
        for label in (self.title, self.subtitle):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._identity = QWidget()
        self._identity.setMinimumWidth(IDENTITY_MIN_WIDTH)
        self._identity.setMaximumWidth(IDENTITY_MAX_WIDTH)
        identity = QVBoxLayout(self._identity)
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(2)
        identity.addWidget(self.title)
        identity.addWidget(self.subtitle)
        row.addWidget(self._identity)

        # "vdivider", not "separator": the separator rule clamps the height to a pixel,
        # which is right for a horizontal rule and made this one 1x1 and invisible.
        self._divider = QFrame()
        self._divider.setProperty("role", "vdivider")
        self._divider.setFixedWidth(1)
        self._divider.setFixedHeight(DIVIDER_HEIGHT)
        row.addWidget(self._divider)

        # Not Ignored, unlike the identity: four counters are about 300 px together, and
        # a number that silently collapses to nothing is worse than no number at all.
        # When the bar runs out of room it is the name that elides and the actions that
        # overflow, both of which say what they did.
        self._counters = QWidget()
        self._counter_row = QHBoxLayout(self._counters)
        self._counter_row.setContentsMargins(0, 0, 0, 0)
        self._counter_row.setSpacing(metrics.space * 2 + 4)
        row.addWidget(self._counters)

        row.addStretch(1)

        self._actions = QWidget()
        self._action_row = QHBoxLayout(self._actions)
        self._action_row.setContentsMargins(0, 0, 0, 0)
        self._action_row.setSpacing(metrics.space)
        row.addWidget(self._actions)

        # What will not fit goes in here rather than widening the bar. The first action
        # a screen gives is the one it is about, and it never overflows.
        self.overflow_button = QToolButton()
        self.overflow_button.setText("…")
        self.overflow_button.setToolTip("More actions")
        self.overflow_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._overflow_menu = QMenu(self.overflow_button)
        self.overflow_button.setMenu(self._overflow_menu)
        self.overflow_button.hide()
        row.addWidget(self.overflow_button)

        self._all_actions: list[QWidget] = []
        self.set_counters([])

    # --- what the window sets ----------------------------------------------

    def set_project(self, name: str, files: int, candidates: int) -> None:
        """Name the project and say how much footage it is made of."""
        subtitle = (
            f"{files} files, {candidates} candidates" if name else "Open or create one to start"
        )
        self._identity_text = (name or "No project open", subtitle)
        self._elide_identity()

    def clear_project(self) -> None:
        self.set_project("", 0, 0)
        self.set_counters([])
        self.set_actions([])

    def set_counters(self, counters: list[Counter]) -> None:
        """Replace the counters. An empty list hides the block and its divider."""
        while self._counter_row.count():
            item = self._counter_row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                # Unparent before deleting: deleteLater only takes effect when the
                # event loop next runs, and until then the old label is still a child
                # and still findable, which made a rebuilt block read as two blocks.
                widget.setParent(None)
                widget.deleteLater()
        for counter in counters:
            self._counter_row.addWidget(self._counter_widget(counter))
        self._counters.setVisible(bool(counters))
        self._divider.setVisible(bool(counters))

    def set_actions(self, actions: list[QWidget]) -> None:
        """Show this screen's buttons. They stay owned by the screen that made them."""
        while self._action_row.count():
            item = self._action_row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
        self._all_actions = list(actions)
        for action in actions:
            self._action_row.addWidget(action)
            action.show()
        self._actions.setVisible(bool(actions))
        self._reflow_actions()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._elide_identity()
        self._reflow_actions()

    def _elide_identity(self) -> None:
        """Cut the project name and its counts to whatever room the block has."""
        room = max(self._identity.width(), IDENTITY_MIN_WIDTH)
        for label, text in zip((self.title, self.subtitle), self._identity_text, strict=True):
            label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, room))
            label.setToolTip(text if label.text() != text else "")

    def _reflow_actions(self) -> None:
        """Move what does not fit into the overflow menu, and back out when it does.

        Measured against the bar's own width rather than a breakpoint, so a long project
        name pushes an action into the menu as readily as a narrow window does.
        """
        if not self._all_actions:
            self.overflow_button.hide()
            return

        room = self.width() - self._identity_width() - self._counters_width()
        shown: list[QWidget] = []
        used = 0
        for index, action in enumerate(self._all_actions):
            width = _effective_width(action) + self._action_row.spacing()
            # The first action always stays: it is the one the screen is about.
            if index == 0 or used + width <= room:
                shown.append(action)
                used += width

        hidden = [action for action in self._all_actions if action not in shown]
        for action in self._all_actions:
            action.setVisible(action in shown)

        self._overflow_menu.clear()
        for action in hidden:
            entry = self._overflow_menu.addAction(_action_label(action))
            entry.triggered.connect(_clicker(action))
        self.overflow_button.setVisible(bool(hidden))

    def _identity_width(self) -> int:
        return max(self._identity.width(), IDENTITY_MIN_WIDTH)

    def _counters_width(self) -> int:
        return self._counters.sizeHint().width() if self._counters.isVisible() else 0

    @property
    def overflowed(self) -> list[str]:
        """The labels now in the overflow menu. Read by the tests."""
        return [entry.text() for entry in self._overflow_menu.actions()]

    # --- building ----------------------------------------------------------

    def _counter_widget(self, counter: Counter) -> QWidget:
        metrics = theme.current().metrics
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        value = QLabel(counter.value)
        value.setFont(theme.font(metrics.counter_size, mono=True, weight=theme.MEDIUM))
        if counter.accent:
            value.setProperty("role", "accent")
        label = QLabel(counter.label.upper())
        label.setProperty("role", "label")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        column.addWidget(value)
        column.addWidget(label)
        return holder

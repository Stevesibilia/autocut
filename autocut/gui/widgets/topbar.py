"""The bar over every screen: what this project is, and what the screen can do.

The counters used to live in the Review screen's header, where they were invisible from
every other screen and where two screens counting the same edit would have had to agree
by hand. They belong to the project, so they belong to the window.

The bar owns none of the behaviour. A screen hands it a line of counters and a row of
its own buttons through `set_counters` and `set_actions`, and the window swaps them when
the screen changes; the buttons stay the screen's, connected to the screen's slots.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from autocut.gui import theme


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

        self.title = QLabel("No project open")
        self.title.setProperty("role", "heading")
        self.subtitle = QLabel("")
        self.subtitle.setProperty("role", "muted")
        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(2)
        identity.addWidget(self.title)
        identity.addWidget(self.subtitle)
        row.addLayout(identity)

        self._divider = QFrame()
        self._divider.setFixedWidth(1)
        self._divider.setFixedHeight(28)
        self._divider.setProperty("role", "separator")
        self._divider.setStyleSheet(f"background: {theme.current().palette.border};")
        row.addWidget(self._divider)

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

        self.set_counters([])

    # --- what the window sets ----------------------------------------------

    def set_project(self, name: str, files: int, candidates: int) -> None:
        """Name the project and say how much footage it is made of."""
        self.title.setText(name or "No project open")
        if name:
            self.subtitle.setText(f"{files} files, {candidates} candidates")
        else:
            self.subtitle.setText("Open or create one to start")

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
        for action in actions:
            self._action_row.addWidget(action)
            action.show()
        self._actions.setVisible(bool(actions))

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

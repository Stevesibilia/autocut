"""The stages of a run, as a card each.

A list of six indented strings with `done` and `->` in front of them told the user
where the run was, but only if they read all six. A card per stage puts the state in an
icon: a tick in the accent for what is finished, the film mark in the accent for what is
running, and nothing at all for what has not started, so the run is one glance.

The counters are in the mono face for the same reason they are on the cards: `12 / 72`
that jumps a pixel every file is harder to read than one that does not.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from autocut.gui import theme
from autocut.gui.theme import icons

ICON_SIZE = 16

#: What a stage can be. `waiting` is drawn as an empty ring rather than an icon, so a
#: run that has not started does not look like six failures.
DONE = "done"
RUNNING = "running"
WAITING = "waiting"


class StageCard(QWidget):
    """One stage: its state, its name, and a counter when it is counting something."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.setObjectName("card")
        metrics = theme.current().metrics

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(metrics.space + 2)

        self.mark = QLabel()
        self.mark.setFixedSize(QSize(ICON_SIZE, ICON_SIZE))
        self.mark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name = QLabel(title)
        self.counter = QLabel("")
        self.counter.setFont(theme.font(metrics.body_size, mono=True))
        self.counter.setProperty("role", "muted")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(self.mark)
        row.addWidget(self.name, 1)
        row.addWidget(self.counter)
        self.set_state(WAITING)

    def set_state(self, state: str) -> None:
        """Draw the mark and decide how loudly the name is written."""
        colors = theme.current().palette
        ratio = float(self.devicePixelRatioF() or 1.0)
        self.state = state
        if state == DONE:
            self.mark.setPixmap(icons.pixmap("check", colors.accent, ICON_SIZE, ratio))
        elif state == RUNNING:
            self.mark.setPixmap(icons.pixmap("film", colors.accent, ICON_SIZE, ratio))
        else:
            self.mark.clear()
        self.name.setProperty("role", None if state == RUNNING else "muted")
        theme.repolish(self.name)

    def set_counter(self, text: str) -> None:
        self.counter.setText(text)


class StageList(QWidget):
    """The cards, in the order the core runs them."""

    def __init__(self, titles: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cards: dict[str, StageCard] = {}
        self.order = [key for key, _ in titles]

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.current().metrics.space)
        for key, title in titles:
            card = StageCard(title)
            self.cards[key] = card
            column.addWidget(card)

    def mark_up_to(self, stage: str) -> None:
        """Tick every stage before `stage`, mark it running, leave the rest waiting."""
        if stage not in self.order:
            return
        position = self.order.index(stage)
        for index, key in enumerate(self.order):
            if index < position:
                self.cards[key].set_state(DONE)
            elif index == position:
                self.cards[key].set_state(RUNNING)
            else:
                self.cards[key].set_state(WAITING)

    def mark_all_done(self) -> None:
        for card in self.cards.values():
            card.set_state(DONE)
            card.set_counter("")

    def reset(self) -> None:
        for card in self.cards.values():
            card.set_state(WAITING)
            card.set_counter("")

    def set_counter(self, stage: str, text: str) -> None:
        card = self.cards.get(stage)
        if card is not None:
            card.set_counter(text)

    def state(self, stage: str) -> str:
        return self.cards[stage].state

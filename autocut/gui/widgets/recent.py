"""Recent projects, as cards rather than as a list of paths.

A row of text answered the wrong question. What a user recognises a project by is its
folder name and roughly when they last touched it, not the absolute path it happens to
live at, and a list of eight identical grey paths made them read every one. A card puts
the name first, the path under it in the muted colour, and the date on the right.

Opening is still a double click on the card, the same gesture the list had.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from autocut.gui import theme

MANIFEST_NAME = "manifest.json"


def touched_label(project: Path, now: datetime | None = None) -> str:
    """How long ago this project was last written, in words.

    From the manifest's modification time rather than the folder's, because a folder's
    time changes when anything at all is written into it, including a thumbnail cache.
    """
    manifest = project / MANIFEST_NAME
    try:
        stamp = datetime.fromtimestamp(manifest.stat().st_mtime)
    except OSError:
        return "never opened"
    delta = (now or datetime.now()) - stamp
    days = delta.days
    if days <= 0:
        hours = delta.seconds // 3600
        if hours < 1:
            return "just now"
        return f"{hours} h ago"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    return stamp.strftime("%d %b %Y")


class RecentCard(QWidget):
    """One project: its name, where it is, and when it was last touched."""

    opened = Signal(str)

    def __init__(self, project: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        metrics = theme.current().metrics

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(metrics.space)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        self.name = QLabel(project.name)
        self.name.setProperty("role", "title")
        self.path = QLabel(str(project.parent))
        self.path.setProperty("role", "muted")
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        column.addWidget(self.name)
        column.addWidget(self.path)

        self.touched = QLabel(touched_label(project))
        self.touched.setProperty("role", "muted")
        self.touched.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addLayout(column, 1)
        row.addWidget(self.touched)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        del event
        self.opened.emit(str(self.project))


class RecentList(QWidget):
    """The cards, newest first, or a sentence when there are none."""

    opened = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(theme.current().metrics.space)
        self.cards: list[RecentCard] = []
        self.empty = QLabel("Nothing here yet. The projects you open will be listed here.")
        self.empty.setWordWrap(True)
        self.empty.setProperty("role", "muted")
        self._column.addWidget(self.empty)
        self._column.addStretch(1)

    def set_projects(self, projects: list[Path]) -> None:
        """Redraw the list. The stretch at the bottom keeps the cards at the top."""
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        for index, project in enumerate(projects):
            card = RecentCard(project)
            card.opened.connect(self.opened.emit)
            self._column.insertWidget(index, card)
            self.cards.append(card)
        self.empty.setVisible(not projects)

"""What a screen shows before it has anything to show.

One sentence and one action, every time. A screen with nothing on it is the moment a
user is most likely to be lost, and a paragraph of explanation there is read by nobody;
the sentence says what is missing and the button does the thing that would fix it.

The widget is deliberately dumb. It carries no state and knows no rules: a screen hands
it the sentence and, when there is something to be done about it, a button of its own.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from autocut.gui import theme
from autocut.gui.theme import icons

ICON_SIZE = 24


class EmptyState(QWidget):
    """An icon, a sentence, and at most one thing to do about it."""

    def __init__(
        self,
        message: str,
        icon: str = "info",
        action: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        colors = theme.current().palette
        metrics = theme.current().metrics

        column = QVBoxLayout(self)
        column.setContentsMargins(0, metrics.space * 4, 0, metrics.space * 4)
        column.setSpacing(metrics.space + 4)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setPixmap(
            icons.pixmap(icon, colors.text_muted, ICON_SIZE, float(self.devicePixelRatioF() or 1.0))
        )

        self.message = QLabel(message)
        self.message.setWordWrap(True)
        self.message.setProperty("role", "muted")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)

        column.addWidget(self.icon)
        column.addWidget(self.message)
        if action is not None:
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(action)
            row.addStretch(1)
            column.addLayout(row)

    def set_message(self, message: str) -> None:
        self.message.setText(message)

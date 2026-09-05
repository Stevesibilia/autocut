"""A screen that says which change will fill it in.

The navigation lists all five screens from the first change, because hiding two of
them and adding them later would change the shape of the window under the user. A
placeholder that names the change is more use than a blank panel.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderScreen(QWidget):
    """A title and one sentence about what is coming."""

    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"placeholder-{title.lower()}")
        heading = QLabel(title)
        heading.setProperty("role", "display")
        body = QLabel(message)
        body.setWordWrap(True)
        body.setProperty("role", "muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

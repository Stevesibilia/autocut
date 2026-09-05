"""A layout that wraps its children onto the next line instead of demanding the width.

A `QHBoxLayout` of eight filter chips reports the sum of their widths as its minimum,
and Qt will not shrink a window below its layout's minimum. That is how the window
ended up 1958 px wide and pinned there on a laptop.

This is the flow layout from the Qt examples, typed and cut down to what the window
needs. The part that matters is `heightForWidth`: the layout answers "give me a width
and I will tell you how tall I need to be", so its minimum width is one item rather
than all of them.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """Left to right, wrapping at the edge, with an even gap between items."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setSpacing(spacing)
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    # --- what QLayout requires ---------------------------------------------

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        """The whole point: the height depends on the width it is given."""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._lay_out(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._lay_out(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        """One line of everything, which is what the row looks like when it fits."""
        margins = self.contentsMargins()
        width = sum(item.sizeHint().width() for item in self._items)
        width += self._spacing * max(len(self._items) - 1, 0)
        height = max((item.sizeHint().height() for item in self._items), default=0)
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        """The widest single item, not the sum. This is the number the window reads."""
        margins = self.contentsMargins()
        width = max((item.minimumSize().width() for item in self._items), default=0)
        height = max((item.minimumSize().height() for item in self._items), default=0)
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    # --- the arithmetic -----------------------------------------------------

    def _lay_out(self, rect: QRect, apply: bool) -> int:
        """Place the items inside `rect`, or measure without moving anything.

        Returns the height the items need at that width, which is what
        `heightForWidth` answers and what makes the row shrink rather than push.
        """
        margins = self.contentsMargins()
        inner = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y = inner.x(), inner.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if line_height and next_x - self._spacing > inner.right() + 1:
                x = inner.x()
                y += line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()


class FlowRow(QWidget):
    """A widget wrapping a `FlowLayout`, so it can be dropped into any layout.

    `heightForWidth` on a bare layout is not consulted by every parent, and a widget
    that answers for itself is understood everywhere.
    """

    def __init__(self, spacing: int = 8, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flow = FlowLayout(self, spacing=spacing)
        self.setLayout(self._flow)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def add(self, widget: QWidget) -> QWidget:
        self._flow.addWidget(widget)
        return widget

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._flow.heightForWidth(width)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self._flow.sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self._flow.minimumSize()

    def lines_at(self, width: int) -> int:
        """How many rows the items fall onto at `width`. For the tests, and for reading."""
        if not self._flow.count():
            return 0
        one = max(self._flow.itemAt(i).sizeHint().height() for i in range(self._flow.count()))  # type: ignore[union-attr]
        total = self._flow.heightForWidth(width)
        return max(round((total + self._flow.spacing()) / (one + self._flow.spacing())), 1)

    def spacing(self) -> int:
        return self._flow.spacing()

    def count(self) -> int:
        return self._flow.count()

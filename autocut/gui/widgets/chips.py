"""The filter row of the Review screen, as pills.

A row of `Sort [combo] Class [combo] Tag [combo] …` spent most of its width on labels
saying what each box was for, and a combo box that reads "any" looks exactly like one
that is filtering the grid down to nine clips. A chip reads `Place  Orrì` in one object
and turns the accent colour when it is actually doing something, so the row says at a
glance what the grid is showing.

Nothing here filters. Each chip is a face for a `QComboBox` that already existed and
still exists: the chip writes the combo's index and the combo tells the chip what it
now says, so `models.SegmentFilterProxy` is untouched and every screen and test that
drives a box directly keeps working.
"""

from __future__ import annotations

from typing import TypeAlias, TypeVar

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from autocut.gui import theme
from autocut.gui.widgets.flow import FlowRow

#: What a chip says when its box is on the entry that filters nothing. Matched against
#: the box's text, so a box whose "everything" entry is worded differently still reads
#: as inactive rather than pretending to filter.
NEUTRAL = {"any", "all", "chronology"}


class FilterChip(QToolButton):
    """One pill over one combo box."""

    def __init__(self, label: str, box: QComboBox, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.box = box
        self.setProperty("chip", True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # The chip adopts its box. Without a parent a QComboBox is a top level window,
        # and a filter row that opened six empty windows is not a subtle bug to find.
        box.setParent(self)
        box.hide()

        self._menu = QMenu(self)
        self._menu.aboutToShow.connect(self._fill)
        self.setMenu(self._menu)

        box.currentIndexChanged.connect(lambda _index: self.refresh())
        self.refresh()

    def _fill(self) -> None:
        """Rebuild the menu from the box, which is refilled whenever a project opens."""
        self._menu.clear()
        for row in range(self.box.count()):
            action = self._menu.addAction(self.box.itemText(row))
            action.setCheckable(True)
            action.setChecked(row == self.box.currentIndex())
            action.triggered.connect(lambda _checked, index=row: self.box.setCurrentIndex(index))

    def refresh(self) -> None:
        """Say what the box says, and look active when it is filtering something."""
        value = self.box.currentText()
        self.setText(f"{self.label}  {value}" if value else self.label)
        self.setProperty("active", value.strip().lower() not in NEUTRAL)
        theme.repolish(self)

    @property
    def active(self) -> bool:
        return bool(self.property("active"))


class RangeChip(QToolButton):
    """The score range, over the two spin boxes that hold it.

    A menu of values makes no sense for a range, so the pill opens the two spin boxes
    themselves. They keep their own signals, so the proxy hears a change the moment it
    is typed rather than when the menu closes.
    """

    def __init__(
        self,
        label: str,
        low: QDoubleSpinBox,
        high: QDoubleSpinBox,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.label = label
        self.low = low
        self.high = high
        self.setProperty("chip", True)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(theme.current().metrics.space)
        row.addWidget(low)
        row.addWidget(QLabel("to"))
        row.addWidget(high)

        action = QWidgetAction(self)
        action.setDefaultWidget(holder)
        self._menu = QMenu(self)
        self._menu.addAction(action)
        self.setMenu(self._menu)

        for box in (low, high):
            box.valueChanged.connect(lambda _value: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        low, high = self.low.value(), self.high.value()
        self.setText(f"{self.label}  {low:.2f} – {high:.2f}")
        whole = low <= self.low.minimum() and high >= self.high.maximum()
        self.setProperty("active", not whole)
        theme.repolish(self)

    @property
    def active(self) -> bool:
        return bool(self.property("active"))


#: Either kind of pill. Both answer `refresh` and `active`, which is all the row wants.
Chip: TypeAlias = FilterChip | RangeChip
ChipT = TypeVar("ChipT", FilterChip, RangeChip)


class FilterChips(QWidget):
    """The whole row: the chips first, then the two view toggles.

    A flow row rather than a box: eight chips in a `QHBoxLayout` reported the sum of
    their widths as the row's minimum, and Qt will not shrink a window below its
    layout's minimum, so the row alone pinned the window at 1111 px before the rail and
    the panel were counted. Wrapping costs a second line on a narrow window and gives
    the width back.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chips: dict[str, Chip] = {}
        self._row = FlowRow(spacing=theme.current().metrics.space)
        holder = QHBoxLayout(self)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(self._row)

    def add_chip(self, key: str, chip: ChipT) -> ChipT:
        """Add a chip. The toggles are added after them and follow on the same flow."""
        self.chips[key] = chip
        self._row.add(chip)
        return chip

    def lines_at(self, width: int) -> int:
        """How many lines the row falls onto at `width`. Read by the tests."""
        return self._row.lines_at(width)

    def add_box(self, key: str, label: str, box: QComboBox) -> FilterChip:
        return self.add_chip(key, FilterChip(label, box))

    def add_range(
        self, key: str, label: str, low: QDoubleSpinBox, high: QDoubleSpinBox
    ) -> RangeChip:
        return self.add_chip(key, RangeChip(label, low, high))

    def add_toggle(self, widget: QWidget) -> None:
        """A view switch, which is not a filter but wraps with the rest of the row."""
        self._row.add(widget)

    def refresh(self) -> None:
        """Re-read every chip, after the boxes were refilled for a new project."""
        for chip in self.chips.values():
            chip.refresh()

    @property
    def active_keys(self) -> list[str]:
        """Which chips are actually filtering. Read by the tests, and by nothing else."""
        return [key for key, chip in self.chips.items() if chip.active]

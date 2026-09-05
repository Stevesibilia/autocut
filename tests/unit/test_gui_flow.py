"""The wrapping row, on its own.

The number that matters is the minimum width. A `QHBoxLayout` reports the sum of its
children and Qt then refuses to shrink the window below it, which is how the window
came out 1958 px wide and pinned there on a laptop. A flow row reports one item.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget  # noqa: E402

from autocut.gui.widgets.flow import FlowRow  # noqa: E402

pytestmark = pytest.mark.gui


def a_row(qtbot: Any, count: int = 8, width: int = 140) -> FlowRow:
    row = FlowRow()
    qtbot.addWidget(row)
    for index in range(count):
        button = QPushButton(f"chip {index}")
        button.setFixedWidth(width)
        button.setFixedHeight(30)
        row.add(button)
    return row


def test_the_minimum_is_one_item_not_the_sum(qtbot: Any) -> None:
    row = a_row(qtbot)
    assert row.count() == 8
    assert row.minimumSizeHint().width() < 200, row.minimumSizeHint().width()


def test_a_box_layout_would_have_demanded_the_sum(qtbot: Any) -> None:
    """The comparison the fix is against, so the number above means something."""
    holder = QWidget()
    qtbot.addWidget(holder)
    box = QHBoxLayout(holder)
    for index in range(8):
        button = QPushButton(f"chip {index}")
        button.setFixedWidth(140)
        box.addWidget(button)

    assert holder.minimumSizeHint().width() > 1100


def test_the_size_hint_is_one_line_of_everything(qtbot: Any) -> None:
    """One line: the sum of the widths, and the height of a single item.

    The height is read off an item rather than written down, because the application
    stylesheet gives a button a minimum height and the number is not this test's to know.
    """
    row = a_row(qtbot)
    hint = row.sizeHint()
    one = row.layout().itemAt(0).sizeHint()

    assert hint.width() >= 8 * 140
    assert hint.height() == one.height()


def test_it_wraps_when_the_width_runs_out(qtbot: Any) -> None:
    row = a_row(qtbot)

    assert row.lines_at(2000) == 1
    assert row.lines_at(700) == 2
    assert row.lines_at(300) == 4


def test_a_taller_row_is_reported_for_a_narrower_width(qtbot: Any) -> None:
    row = a_row(qtbot)
    assert row.heightForWidth(2000) < row.heightForWidth(700) < row.heightForWidth(300)


def test_an_empty_row_measures_nothing(qtbot: Any) -> None:
    row = FlowRow()
    qtbot.addWidget(row)
    assert row.count() == 0
    assert row.lines_at(800) == 0
    assert row.minimumSizeHint().width() == 0


def test_the_items_are_actually_placed_on_two_lines(qtbot: Any) -> None:
    """`lines_at` is arithmetic; this checks the geometry Qt ends up with."""
    row = a_row(qtbot)
    row.resize(700, row.heightForWidth(700))
    row.show()
    qtbot.waitExposed(row)

    tops = {row.layout().itemAt(i).widget().y() for i in range(row.count())}
    assert len(tops) == 2, tops


def test_taking_an_item_out_shrinks_the_row(qtbot: Any) -> None:
    row = a_row(qtbot)
    before = row.sizeHint().width()

    item = row.layout().takeAt(0)
    assert item is not None

    assert row.sizeHint().width() < before
    assert row.count() == 7

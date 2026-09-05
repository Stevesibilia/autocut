"""The generated stylesheet, for both token sets.

Two things can go wrong with a stylesheet built from a template and neither of them
raises: a placeholder survives the render and Qt drops the rule that contained it, or
a selector is misspelled and Qt writes a warning nobody reads. Both are checked here,
against the real `QApplication`, because a stylesheet is only correct once Qt has
parsed it.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from autocut.gui.theme import qss, tokens  # noqa: E402

pytestmark = pytest.mark.gui

THEMES = [tokens.THEMES["dark"], tokens.THEMES["light"]]
IDS = [theme.name for theme in THEMES]


def styled_widgets() -> QWidget:
    """One widget of every kind the stylesheet has a rule for, in a single parent.

    A rule Qt cannot parse is only reported when a widget it applies to is polished,
    so a sheet is only proven good by building the widgets under it.
    """
    holder = QWidget()
    holder.setObjectName("card")
    column = QVBoxLayout(holder)

    chip = QToolButton()
    chip.setProperty("chip", True)
    rail_item = QToolButton()
    rail_item.setProperty("rail", True)
    primary = QPushButton("Play all")
    primary.setProperty("variant", "primary")
    quiet = QPushButton("Play clip")
    quiet.setProperty("variant", "quiet")
    weights = QSlider()
    weights.setProperty("variant", "weight")
    labels = [QLabel("x") for _ in range(8)]
    for label, role in zip(
        labels,
        ("heading", "title", "muted", "label", "counter", "display", "accent", "placeholder"),
        strict=True,
    ):
        label.setProperty("role", role)

    for widget in (
        *labels,
        primary,
        quiet,
        QPushButton("Export report"),
        chip,
        rail_item,
        QLineEdit(),
        QComboBox(),
        QDoubleSpinBox(),
        QCheckBox("Sound"),
        QSlider(),
        weights,
        QProgressBar(),
        QGroupBox("Weights"),
        QListWidget(),
        QScrollArea(),
    ):
        column.addWidget(widget)
    return holder


#: The offscreen platform announces this on every show and it has nothing to do with
#: a stylesheet. Everything else Qt says during these tests is a real complaint.
PLATFORM_NOISE = ("propagateSizeHints",)


@pytest.fixture
def qt_messages() -> Any:
    """Every complaint Qt makes while the fixture is in place."""
    collected: list[str] = []

    def handler(mode: QtMsgType, context: Any, message: str) -> None:
        del context
        if mode not in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            return
        if any(noise in message for noise in PLATFORM_NOISE):
            return
        collected.append(message)

    previous = qInstallMessageHandler(handler)
    try:
        yield collected
    finally:
        qInstallMessageHandler(previous)


@pytest.mark.parametrize("theme", THEMES, ids=IDS)
def test_the_render_leaves_no_placeholder(theme: tokens.Theme) -> None:
    sheet = qss.stylesheet(theme)
    assert sheet.strip()
    assert qss.unresolved(sheet) == []


def test_the_placeholder_check_would_catch_one() -> None:
    """A check that never fires is not a check."""
    assert qss.unresolved("QLabel { color: $accent; }") == ["$accent"]
    assert qss.unresolved("QLabel { color: ${accent}; }") == ["${accent}"]
    assert qss.unresolved("QLabel { color: {accent}; }") == ["{accent}"]
    assert qss.unresolved("QLabel { color: #e6e4de; }") == []


@pytest.mark.parametrize("theme", THEMES, ids=IDS)
def test_the_sheet_carries_the_colours_of_its_own_theme(theme: tokens.Theme) -> None:
    sheet = qss.stylesheet(theme)
    other = tokens.LIGHT if theme.palette is tokens.DARK else tokens.DARK
    assert theme.palette.accent in sheet
    assert theme.palette.background in sheet
    assert other.accent not in sheet


@pytest.mark.parametrize("theme", THEMES, ids=IDS)
def test_qt_parses_the_sheet_without_a_word(
    qapp: QApplication, qtbot: Any, qt_messages: list[str], theme: tokens.Theme
) -> None:
    """Qt reports a bad rule when it polishes a widget, not when the sheet is set.

    So the sheet is installed on the application and then one widget of every kind it
    styles is built and polished under it. Anything the template got wrong, including
    a placeholder that survived the render, shows up here as a parse warning.
    """
    previous = qapp.styleSheet()
    try:
        qapp.setStyleSheet(qss.stylesheet(theme))
        window = styled_widgets()
        qtbot.addWidget(window)
        window.show()
        qapp.processEvents()
    finally:
        qapp.setStyleSheet(previous)
    assert qt_messages == []


def test_a_broken_sheet_does_make_qt_complain(qapp: QApplication, qt_messages: list[str]) -> None:
    """Proof the handler above is actually listening to Qt."""
    label = QLabel("x")
    label.setStyleSheet("QLabel { color: $accent; }")
    # Polishing is what makes Qt parse it. The label is never shown and never queued
    # for deletion, so it cannot come back and warn again inside somebody else's test.
    label.ensurePolished()
    qapp.processEvents()
    assert qt_messages


def test_stylesheet_defaults_to_the_active_theme() -> None:
    try:
        tokens.activate("light")
        assert tokens.LIGHT.accent in qss.stylesheet()
    finally:
        tokens.activate("dark")
    assert tokens.DARK.accent in qss.stylesheet()


def test_every_token_is_spelled_the_way_the_template_asks() -> None:
    """`substitute` raises on an unknown name, so rendering both sets is the check."""
    for theme in THEMES:
        qss.stylesheet(theme)

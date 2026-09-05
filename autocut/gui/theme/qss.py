"""The application stylesheet, rendered from the active tokens.

One template for the whole window. Qt's Fusion style honours a stylesheet the same way
on Linux and on macOS (ADR 10), so this file plus the palette in `app.apply_theme` is
the entire difference between the two platforms looking alike and looking like two
applications.

The placeholders are `$name`, not `{name}`: QSS is made of braces, and a template that
had to double every one of them would be unreadable and would break the first time
someone forgot. `string.Template.substitute` still raises on a name that is not a
token, so a typo fails loudly at the first render rather than shipping a rule Qt
silently drops.

Selectors that carry meaning rather than a class name are set through properties, so a
widget asks for a look by saying what it is:

    button.setProperty("variant", "primary")   # the one action a screen is about
    button.setProperty("chip", True)           # a filter pill
    label.setProperty("role", "muted")         # a caption, a unit, a label

After changing a property on a widget that is already shown, unpolish and repolish it
or Qt keeps the old rule. `repolish` below does that.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from string import Template

from PySide6.QtWidgets import QWidget

from autocut.gui.theme.tokens import Theme, current

#: Anything that looks like an unresolved placeholder, in either spelling. The test
#: suite runs this over the rendered sheet, because a placeholder Qt cannot parse
#: takes the rest of its rule with it and the window just quietly looks wrong.
PLACEHOLDER = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\{[A-Za-z_][A-Za-z0-9_]*\}")

TEMPLATE = Template("""
/* --- the window and its regions ------------------------------------------ */

QWidget {
    background: $background;
    color: $text;
    font-size: ${body_size}px;
}

QMainWindow, QDialog {
    background: $background;
}

QWidget#navRail {
    background: $rail;
    border-right: 1px solid $border;
}

QWidget#topBar {
    background: $background;
    border-bottom: 1px solid $border;
}

QWidget#rightPanel {
    background: $background;
    border-left: 1px solid $border;
}

QWidget#card, QFrame#card {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${radius_card}px;
}

QFrame[role="separator"] {
    background: $border;
    border: none;
    max-height: 1px;
    min-height: 1px;
}

/* The upright one. It needs its own role because the clamp above is on the height,
   and a vertical divider that inherited it collapsed to a single pixel and vanished. */
QFrame[role="vdivider"] {
    background: $border;
    border: none;
    max-width: 1px;
    min-width: 1px;
}

/* --- text ---------------------------------------------------------------- */

QLabel {
    background: transparent;
    color: $text;
}

QLabel[role="heading"] {
    font-size: ${heading_size}px;
    font-weight: 600;
}

QLabel[role="title"] {
    font-size: ${title_size}px;
    font-weight: 600;
}

QLabel[role="muted"] {
    color: $text_muted;
}

QLabel[role="label"] {
    color: $text_muted;
    font-size: ${label_size}px;
    text-transform: uppercase;
}

QLabel[role="counter"] {
    font-size: ${counter_size}px;
    font-weight: 500;
}

QLabel[role="display"] {
    font-size: ${display_size}px;
    font-weight: 600;
}

QLabel[role="accent"] {
    color: $accent;
}

QLabel[role="warning"] {
    color: $amber;
}

QLabel[role="error"] {
    color: $red;
}

QLabel[role="placeholder"] {
    background: $surface;
    color: $text_muted;
    border-radius: ${radius_control}px;
}

/* --- buttons ------------------------------------------------------------- */

QPushButton {
    background: transparent;
    border: 1px solid $border_strong;
    border-radius: ${radius_control}px;
    color: $text_secondary;
    font-size: ${title_size}px;
    min-height: ${control_height}px;
    padding: 0 14px;
}

QPushButton:hover {
    border-color: $border_muted;
    color: $text;
}

QPushButton:pressed {
    background: $surface_hover;
}

QPushButton:disabled {
    border-color: $border;
    color: $text_muted;
}

QPushButton[variant="primary"] {
    background: $accent;
    border: 1px solid $accent;
    color: $on_accent;
    font-weight: 600;
}

QPushButton[variant="primary"]:hover {
    background: $accent_weight;
    border-color: $accent_weight;
}

QPushButton[variant="primary"]:disabled {
    background: $surface_raised;
    border-color: $surface_raised;
    color: $text_muted;
}

QPushButton[variant="quiet"] {
    background: $accent_surface;
    border: 1px solid transparent;
    color: $accent;
    font-weight: 500;
}

QPushButton[variant="danger"] {
    border-color: $red;
    color: $red;
}

QPushButton[variant="compact"] {
    padding: 0 4px;
}

QPushButton:flat {
    border: none;
}

/* --- chips and rail items ------------------------------------------------ */

QToolButton {
    background: transparent;
    border: none;
    border-radius: ${radius_control}px;
    color: $text_secondary;
    font-size: ${title_size}px;
    padding: 6px 10px;
}

QToolButton:hover {
    background: $surface_hover;
    color: $text;
}

QToolButton[chip="true"] {
    background: $surface_hover;
    border-radius: ${radius_pill}px;
    color: $text_secondary;
    font-size: ${body_size}px;
    padding: 6px 12px;
}

QToolButton[chip="true"]:checked, QToolButton[chip="true"][active="true"] {
    background: $accent_surface;
    color: $accent;
    font-weight: 500;
}

QToolButton[rail="true"] {
    color: $text_muted;
    padding: 9px 10px;
    text-align: left;
}

QToolButton[rail="true"]:hover {
    background: $surface_hover;
    color: $text_secondary;
}

QToolButton[rail="true"]:checked {
    background: $accent_surface;
    color: $accent;
    font-weight: 500;
}

QToolButton[rail="true"]:disabled {
    background: transparent;
    color: $border_muted;
}

QToolButton::menu-indicator {
    image: none;
    width: 0;
}

/* --- inputs -------------------------------------------------------------- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${radius_control}px;
    color: $text;
    padding: 5px 8px;
    selection-background-color: $accent_muted;
    selection-color: $text;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: $accent;
}

QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: $text_muted;
}

QLineEdit, QSpinBox, QDoubleSpinBox {
    min-height: ${control_height}px;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: $surface_raised;
    border: none;
    width: 16px;
}

QComboBox {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${radius_control}px;
    color: $text;
    min-height: ${control_height}px;
    padding: 5px 10px;
}

QComboBox:hover {
    border-color: $border_muted;
}

QComboBox:focus, QComboBox:on {
    border-color: $accent;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${radius_control}px;
    color: $text;
    outline: none;
    padding: 4px;
    selection-background-color: $accent_surface;
    selection-color: $accent;
}

/* --- toggles ------------------------------------------------------------- */

QCheckBox, QRadioButton {
    background: transparent;
    color: $text_secondary;
    spacing: 8px;
}

QCheckBox::indicator, QRadioButton::indicator {
    background: $surface;
    border: 1px solid $border_muted;
    height: 14px;
    width: 14px;
}

QCheckBox::indicator {
    border-radius: 4px;
}

QRadioButton::indicator {
    border-radius: 8px;
}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: $accent;
    border-color: $accent;
}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    border-color: $border;
}

/* --- sliders ------------------------------------------------------------- */

QSlider::groove:horizontal {
    background: $track_bed;
    border-radius: 3px;
    height: 6px;
}

QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 3px;
}

QSlider::add-page:horizontal {
    background: $track_bed;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: $text;
    border-radius: 8px;
    height: 16px;
    margin: -5px 0;
    width: 16px;
}

QSlider::handle:horizontal:disabled {
    background: $border_muted;
}

QSlider[variant="weight"]::sub-page:horizontal {
    background: $accent_weight;
}

QSlider[variant="weight"]::groove:horizontal {
    height: 4px;
}

QSlider[variant="weight"]::handle:horizontal {
    height: 12px;
    margin: -4px 0;
    width: 12px;
}

/* --- progress ------------------------------------------------------------ */

QProgressBar {
    background: $track_bed;
    border: none;
    border-radius: 3px;
    color: $text_muted;
    font-size: ${label_size}px;
    height: 6px;
    text-align: center;
}

QProgressBar::chunk {
    background: $accent;
    border-radius: 3px;
}

/* --- containers ---------------------------------------------------------- */

QGroupBox {
    background: $surface;
    border: 1px solid $border;
    border-radius: ${radius_control}px;
    font-size: ${title_size}px;
    font-weight: 600;
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
}

QGroupBox::title {
    color: $text;
    left: 12px;
    padding: 0 4px;
    subcontrol-origin: margin;
    subcontrol-position: top left;
}

QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}

QStackedWidget {
    background: transparent;
}

QTabWidget::pane {
    background: $surface;
    border: 1px solid $border;
    border-radius: ${radius_control}px;
}

QTabBar::tab {
    background: transparent;
    color: $text_muted;
    padding: 8px 14px;
}

QTabBar::tab:selected {
    color: $accent;
}

QSplitter::handle {
    background: $border;
}

/* --- item views ---------------------------------------------------------- */

QListView, QTreeView, QTableView, QListWidget {
    background: $background;
    border: none;
    color: $text;
    outline: none;
    selection-background-color: $accent_surface;
    selection-color: $accent;
}

QListView::item, QTreeView::item, QListWidget::item {
    border-radius: ${radius_badge}px;
    padding: 6px 8px;
}

QListView::item:hover, QTreeView::item:hover, QListWidget::item:hover {
    background: $surface_hover;
}

QListView::item:selected, QTreeView::item:selected, QListWidget::item:selected {
    background: $accent_surface;
    color: $accent;
}

QHeaderView::section {
    background: $background;
    border: none;
    border-bottom: 1px solid $border;
    color: $text_muted;
    font-size: ${label_size}px;
    padding: 6px 8px;
}

/* --- scroll bars --------------------------------------------------------- */

QScrollBar:vertical {
    background: transparent;
    margin: 0;
    width: 10px;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $border_strong;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    min-height: 32px;
}

QScrollBar::handle:horizontal {
    min-width: 32px;
}

QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: $border_muted;
}

QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* --- menus, tips and the status bar -------------------------------------- */

QMenu {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${radius_control}px;
    padding: 4px;
}

QMenu::item {
    border-radius: ${radius_badge}px;
    padding: 6px 22px 6px 12px;
}

QMenu::item:selected {
    background: $accent_surface;
    color: $accent;
}

QMenu::separator {
    background: $border;
    height: 1px;
    margin: 4px 8px;
}

QToolTip {
    background: $surface_raised;
    border: 1px solid $border_strong;
    border-radius: ${radius_badge}px;
    color: $text;
    padding: 5px 8px;
}

QStatusBar {
    background: $background;
    border-top: 1px solid $border;
    color: $text_muted;
    font-size: ${body_size}px;
}

QStatusBar::item {
    border: none;
}
""")


def stylesheet(theme: Theme | None = None) -> str:
    """The whole stylesheet for `theme`, defaulting to the active one."""
    active = theme or current()
    values: dict[str, object] = {**asdict(active.palette), **asdict(active.metrics)}
    return TEMPLATE.substitute(values)


def unresolved(sheet: str) -> list[str]:
    """Every placeholder the render left behind. Empty is the only healthy answer."""
    return PLACEHOLDER.findall(sheet)


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet to `widget` after one of its properties changed.

    Qt matches property selectors when a widget is polished and does not watch the
    property afterwards, so a chip that becomes active keeps the inactive rule until
    it is unpolished and polished again.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()

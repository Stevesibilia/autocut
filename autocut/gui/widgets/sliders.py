"""The sliders that make the edit answer back.

On the screen rather than in a settings dialog, because the whole promise of section
11 is that a weight is something you turn while looking at the result. Every move goes
through the state's debounce, and none of them decodes video: weights re-score the
metrics already in the manifest, diversity re-runs the greedy loop over cached arrays.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from autocut.core.score import SCORED_METRICS
from autocut.gui import theme
from autocut.gui.state import ProjectState

#: Sliders are integers, weights are not. One step is a hundredth.
STEPS_PER_UNIT = 100
MAX_WEIGHT = 3.0

#: The two fixed columns of a weight row, so six of them line up as a table.
WEIGHT_NAME_WIDTH = 88
WEIGHT_VALUE_WIDTH = 34

#: What the two ends of the diversity slider mean, in the words the mockup used.
DIVERSITY_ENDS = ("best only", "most varied")


def to_slider(value: float) -> int:
    return int(round(value * STEPS_PER_UNIT))


def from_slider(value: int) -> float:
    return value / STEPS_PER_UNIT


def _section(
    title: str, trailing: QWidget, contents: list[Any], metrics: theme.Metrics
) -> QVBoxLayout:
    """A heading with something on its right, then the controls under it."""
    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(metrics.space + 2)

    heading = QHBoxLayout()
    heading.setContentsMargins(0, 0, 0, 0)
    label = QLabel(title)
    label.setProperty("role", "title")
    heading.addWidget(label)
    heading.addStretch(1)
    heading.addWidget(trailing)
    column.addLayout(heading)

    for item in contents:
        if isinstance(item, QWidget):
            column.addWidget(item)
        else:
            column.addLayout(item)
    return column


def _ends() -> QHBoxLayout:
    """The two words under the diversity slider that say which way is which."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    low, high = (QLabel(word) for word in DIVERSITY_ENDS)
    for label in (low, high):
        label.setProperty("role", "muted")
    row.addWidget(low)
    row.addStretch(1)
    row.addWidget(high)
    return row


class SliderPanel(QWidget):
    """One slider per scored metric, plus diversity, plus a reset.

    The metric list comes from the core's own table rather than from a copy here, so a
    metric the scoring learns about appears on the screen without this file changing,
    and one it stops using disappears.
    """

    changed = Signal()

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._sliders: dict[str, QSlider] = {}
        self._values: dict[str, QLabel] = {}

        metrics = theme.current().metrics

        weights_rows = QVBoxLayout()
        weights_rows.setContentsMargins(0, 0, 0, 0)
        weights_rows.setSpacing(metrics.space + 2)
        for _metric, weight_name, _lower_is_better in SCORED_METRICS:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setProperty("variant", "weight")
            slider.setRange(0, to_slider(MAX_WEIGHT))
            slider.setValue(to_slider(float(getattr(state.config.weights, weight_name))))
            slider.valueChanged.connect(lambda _value, name=weight_name: self._weight_moved(name))
            label = QLabel(f"{from_slider(slider.value()):.2f}")
            label.setFont(theme.font(metrics.body_size, mono=True))
            label.setProperty("role", "muted")
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setFixedWidth(WEIGHT_VALUE_WIDTH)
            name_label = QLabel(weight_name)
            name_label.setFixedWidth(WEIGHT_NAME_WIDTH)

            # Name, bar and value on one line: six of them read as a column of numbers
            # rather than as six stacked controls, which is what the mockup asked for.
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(metrics.space + 4)
            row.addWidget(name_label)
            row.addWidget(slider, 1)
            row.addWidget(label)
            weights_rows.addLayout(row)
            self._sliders[weight_name] = slider
            self._values[weight_name] = label

        self.diversity = QSlider(Qt.Orientation.Horizontal)
        self.diversity.setRange(0, STEPS_PER_UNIT)
        self.diversity.setValue(to_slider(state.config.selection.diversity_lambda))
        self.diversity.valueChanged.connect(self._diversity_moved)
        self.diversity_label = QLabel(f"{from_slider(self.diversity.value()):.2f}")
        self.diversity_label.setFont(theme.font(metrics.body_size, mono=True))
        self.diversity_label.setProperty("role", "accent")

        self.reset_button = QPushButton("reset")
        self.reset_button.setFlat(True)
        self.reset_button.setProperty("role", "muted")
        self.reset_button.setToolTip("Back to the values this project was opened with")
        self.reset_button.clicked.connect(self.reset)

        # Diversity first and the weights under it: diversity is the one control that
        # changes which clips win without changing what any of them scores, so it is the
        # one a reviewer reaches for first.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.space * 2)
        layout.addLayout(
            _section("Diversity", self.diversity_label, [self.diversity, _ends()], metrics)
        )
        layout.addLayout(_section("Weights", self.reset_button, [weights_rows], metrics))
        layout.addStretch(1)

        self._defaults = {
            name: float(getattr(state.config.weights, name)) for name in self._sliders
        }
        self._default_diversity = state.config.selection.diversity_lambda

    # --- the two things a slider can mean ----------------------------------

    def _weight_moved(self, name: str) -> None:
        """A weight changes the scores, so the grid has to be re-scored and re-sorted."""
        value = from_slider(self._sliders[name].value())
        setattr(self._state.config.weights, name, value)
        self._values[name].setText(f"{value:.2f}")
        self._state.request_reselect(rescore_first=True)
        self.changed.emit()

    def _diversity_moved(self) -> None:
        """Diversity changes nothing about the clips, only which of them win."""
        value = from_slider(self.diversity.value())
        self._state.config.selection.diversity_lambda = value
        self.diversity_label.setText(f"{value:.2f}")
        self._state.request_reselect()
        self.changed.emit()

    # --- reading and setting from outside ----------------------------------

    def weight(self, name: str) -> float:
        return from_slider(self._sliders[name].value())

    def set_weight(self, name: str, value: float) -> None:
        self._sliders[name].setValue(to_slider(value))

    def set_diversity(self, value: float) -> None:
        self.diversity.setValue(to_slider(value))

    def reset(self) -> None:
        """Back to the values the project was opened with, in one re-selection.

        The signals are blocked while the sliders move so a reset is one edit and not
        one per slider, each of them re-selecting on the way past.
        """
        for name, slider in self._sliders.items():
            slider.blockSignals(True)
            slider.setValue(to_slider(self._defaults[name]))
            slider.blockSignals(False)
            setattr(self._state.config.weights, name, self._defaults[name])
            self._values[name].setText(f"{self._defaults[name]:.2f}")
        self.diversity.blockSignals(True)
        self.diversity.setValue(to_slider(self._default_diversity))
        self.diversity.blockSignals(False)
        self._state.config.selection.diversity_lambda = self._default_diversity
        self.diversity_label.setText(f"{self._default_diversity:.2f}")
        self._state.request_reselect(rescore_first=True, immediate=True)
        self.changed.emit()

    def adopt_config(self) -> None:
        """Read the sliders back from the configuration, without re-selecting.

        Opening another project, or the settings dialog changing a weight, has to move
        these; moving them must not then start an edit the user did not ask for.
        """
        for name, slider in self._sliders.items():
            slider.blockSignals(True)
            value = float(getattr(self._state.config.weights, name))
            slider.setValue(to_slider(value))
            self._values[name].setText(f"{value:.2f}")
            slider.blockSignals(False)
        self.diversity.blockSignals(True)
        self.diversity.setValue(to_slider(self._state.config.selection.diversity_lambda))
        self.diversity_label.setText(f"{self._state.config.selection.diversity_lambda:.2f}")
        self.diversity.blockSignals(False)

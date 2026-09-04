"""The sliders that make the edit answer back.

On the screen rather than in a settings dialog, because the whole promise of section
11 is that a weight is something you turn while looking at the result. Every move goes
through the state's debounce, and none of them decodes video: weights re-score the
metrics already in the manifest, diversity re-runs the greedy loop over cached arrays.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from autocut.core.score import SCORED_METRICS
from autocut.gui.state import ProjectState

#: Sliders are integers, weights are not. One step is a hundredth.
STEPS_PER_UNIT = 100
MAX_WEIGHT = 3.0


def to_slider(value: float) -> int:
    return int(round(value * STEPS_PER_UNIT))


def from_slider(value: int) -> float:
    return value / STEPS_PER_UNIT


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

        weights_box = QGroupBox("Scoring weights")
        form = QFormLayout(weights_box)
        for _metric, weight_name, _lower_is_better in SCORED_METRICS:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, to_slider(MAX_WEIGHT))
            slider.setValue(to_slider(float(getattr(state.config.weights, weight_name))))
            slider.valueChanged.connect(lambda _value, name=weight_name: self._weight_moved(name))
            label = QLabel(f"{from_slider(slider.value()):.2f}")
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider)
            row_layout.addWidget(label)
            form.addRow(weight_name, row)
            self._sliders[weight_name] = slider
            self._values[weight_name] = label

        self.diversity = QSlider(Qt.Orientation.Horizontal)
        self.diversity.setRange(0, STEPS_PER_UNIT)
        self.diversity.setValue(to_slider(state.config.selection.diversity_lambda))
        self.diversity.valueChanged.connect(self._diversity_moved)
        self.diversity_label = QLabel(f"{from_slider(self.diversity.value()):.2f}")

        diversity_box = QGroupBox("Diversity")
        diversity_layout = QVBoxLayout(diversity_box)
        diversity_layout.addWidget(
            QLabel("How hard a clip is penalised for looking like one already chosen.")
        )
        diversity_layout.addWidget(self.diversity)
        diversity_layout.addWidget(self.diversity_label)

        self.reset_button = QPushButton("Reset to the profile")
        self.reset_button.clicked.connect(self.reset)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(diversity_box)
        layout.addWidget(weights_box)
        layout.addWidget(self.reset_button)
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

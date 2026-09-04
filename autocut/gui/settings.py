"""The settings dialog, and writing what it changes to ``autocut.toml``.

The file is written next to the manifest so the command line sees the same project
the window does: a user who tunes the weights in the dialog and then runs
``autocut select`` on that folder gets the tuned weights. Keys the dialog does not
know about are read back and written out again untouched, so hand editing the file
and using the dialog are not mutually exclusive.

Comments in an existing file do not survive a write. The alternative is a full
round tripping TOML editor as a new dependency, which is a large amount of machinery
for a file the GUI user is not expected to be reading.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from autocut.core.cache import cache_stats
from autocut.core.config import AutocutConfig
from autocut.core.providers import clear_key, find_key, set_key
from autocut.gui.profiles import read_path, write_path
from autocut.gui.state import ProjectState

#: The fields the dialog edits, as dotted paths. Everything else in ``autocut.toml``
#: stays whatever it was.
EDITED_PATHS: tuple[str, ...] = (
    "providers.cloud",
    "providers.describe_scope",
    "analysis.hwaccel",
    "analysis.workers",
    "cache.dir",
    "weights.sharpness",
    "weights.motion",
    "weights.stability",
    "weights.colorfulness",
    "selection.max_clips",
    "selection.diversity_lambda",
)


def _toml_value(value: Any) -> str:
    """One TOML scalar. Only the shapes ``EDITED_PATHS`` can produce."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, Path):
        return _quote(str(value))
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return _quote(str(value))


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dumps_toml(data: dict[str, Any]) -> str:
    """A TOML document from one level of tables of scalars.

    Written here rather than taken as a dependency because that is the whole shape
    ``autocut.toml`` has: tables of scalars, with the nested tables the config uses
    for per class values. A table whose value is another table is emitted as a
    dotted section, which is what ``tomllib`` reads back.
    """
    lines: list[str] = []
    scalars = {key: value for key, value in data.items() if not isinstance(value, dict)}
    tables = {key: value for key, value in data.items() if isinstance(value, dict)}
    for key, value in scalars.items():
        lines.append(f"{key} = {_toml_value(value)}")
    for name, table in tables.items():
        if lines:
            lines.append("")
        lines.append(f"[{name}]")
        nested = {key: value for key, value in table.items() if isinstance(value, dict)}
        for key, value in table.items():
            if key not in nested:
                lines.append(f"{key} = {_toml_value(value)}")
        for sub_name, sub_table in nested.items():
            lines.append("")
            lines.append(f"[{name}.{sub_name}]")
            for key, value in sub_table.items():
                lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def write_config(config: AutocutConfig, path: Path, paths: tuple[str, ...] = EDITED_PATHS) -> None:
    """Merge the edited fields of ``config`` into the TOML at ``path``.

    A value that is ``None`` is left out rather than written as an empty string, since
    the config's own default for those fields means "work it out", and a null is not
    something TOML can say.
    """
    existing: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as fh:
            existing = tomllib.load(fh)
    for dotted in paths:
        value = read_path(config, dotted)
        parts = dotted.split(".")
        table = existing
        for part in parts[:-1]:
            nested = table.get(part)
            if not isinstance(nested, dict):
                nested = {}
                table[part] = nested
            table = nested
        if value is None:
            table.pop(parts[-1], None)
        else:
            table[parts[-1]] = str(value) if isinstance(value, Path) else value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_toml(existing), encoding="utf-8")


class SettingsDialog(QDialog):
    """Cloud, key, decoder, cache and the four weights a non-CLI user will want.

    Bound to the state's configuration rather than to a copy: accepting writes the
    values into it and then to ``autocut.toml``, and cancelling leaves both alone,
    because nothing was written until accept.
    """

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._state = state
        config = state.config

        form = QFormLayout()
        self.cloud = QCheckBox("Send thumbnails to a hosted model")
        self.cloud.setChecked(config.providers.cloud)
        form.addRow("Cloud", self.cloud)

        self.scope = QComboBox()
        self.scope.addItems(["selected", "candidates"])
        self.scope.setCurrentText(str(config.providers.describe_scope))
        form.addRow("Describe", self.scope)

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("stored" if find_key() else "not stored")
        form.addRow("API key", self.key)
        self.forget_key = QPushButton("Forget the stored key")
        self.forget_key.clicked.connect(self._forget_key)
        form.addRow("", self.forget_key)

        self.hwaccel = QComboBox()
        self.hwaccel.addItems(["auto", "off", "videotoolbox", "vaapi"])
        self.hwaccel.setCurrentText(str(config.analysis.hwaccel))
        form.addRow("Decoder", self.hwaccel)

        self.workers = QSpinBox()
        self.workers.setRange(0, 64)
        self.workers.setSpecialValueText("cores")
        self.workers.setValue(config.analysis.workers or 0)
        form.addRow("Parallel files", self.workers)

        self.cache_dir = QLineEdit(str(config.cache.dir) if config.cache.dir else "")
        self.cache_dir.setPlaceholderText("platform cache directory")
        form.addRow("Cache folder", self.cache_dir)

        stats = cache_stats(config)
        self.cache_label = QLabel(
            f"{stats.entries} entries, {stats.bytes / 1e6:.0f} MB in {stats.directory}"
        )
        self.cache_label.setWordWrap(True)
        form.addRow("", self.cache_label)

        self.weights: dict[str, QDoubleSpinBox] = {}
        for name in ("sharpness", "motion", "stability", "colorfulness"):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 5.0)
            spin.setSingleStep(0.1)
            spin.setValue(float(getattr(config.weights, name)))
            form.addRow(f"Weight: {name}", spin)
            self.weights[name] = spin

        self.max_clips = QSpinBox()
        self.max_clips.setRange(1, 500)
        self.max_clips.setValue(config.selection.max_clips)
        form.addRow("Maximum clips", self.max_clips)

        self.diversity = QDoubleSpinBox()
        self.diversity.setRange(0.0, 1.0)
        self.diversity.setSingleStep(0.05)
        self.diversity.setValue(config.selection.diversity_lambda)
        form.addRow("Diversity", self.diversity)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _forget_key(self) -> None:
        removed = clear_key()
        self.key.clear()
        self.key.setPlaceholderText("not stored" if removed else "nothing was stored")

    def accept(self) -> None:
        """Apply to the config, store the key if one was typed, write the file."""
        config = self._state.config
        config.providers.cloud = self.cloud.isChecked()
        write_path(config, "providers.describe_scope", self.scope.currentText())
        write_path(config, "analysis.hwaccel", self.hwaccel.currentText())
        config.analysis.workers = self.workers.value() or None
        typed = self.cache_dir.text().strip()
        config.cache.dir = Path(typed) if typed else None
        for name, spin in self.weights.items():
            setattr(config.weights, name, spin.value())
        config.selection.max_clips = self.max_clips.value()
        config.selection.diversity_lambda = self.diversity.value()

        secret = self.key.text().strip()
        if secret:
            try:
                set_key(secret)
            except Exception as error:  # noqa: BLE001 - no keychain backend is common
                QMessageBox.warning(self, "Key not stored", str(error))
        self.key.clear()

        path = self._state.config_path
        if path is not None:
            write_config(config, path)
        super().accept()

"""The three prompt blocks, editable, with the validator marking what it rejects.

Suno's rules are the reason the validator exists, and the reason it reports a line
number for every violation: a prompt is pasted into a web form, so a rule broken on
line nine has to be visible on line nine and not in a paragraph underneath. Copy is
the point of the screen, so it is one button per block.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from autocut.core.config import AutocutConfig
from autocut.core.manifest import PromptSource, PromptVariant
from autocut.core.soundtrack.validate import Violation, validate_prompt

#: Long enough that typing is not revalidated per keystroke, short enough that the
#: marks feel like they belong to the edit.
VALIDATE_DEBOUNCE_MS = 150

UNDERLINE = QColor(210, 80, 80)


class PromptEditor(QWidget):
    """Title, Description and Structure, each copyable, the last two validated live."""

    changed = Signal()
    """The text was edited by hand, and the validity may have changed with it."""

    def __init__(self, config: AutocutConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._instruments: tuple[str, ...] = ()
        self.violations: list[Violation] = []

        self.title = QLineEdit()
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(70)
        self.structure = QPlainTextEdit()
        self.structure.setMinimumHeight(260)
        for editor in (self.description, self.structure):
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            editor.textChanged.connect(self._text_changed)
        self.title.textChanged.connect(self._text_changed)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setTextFormat(Qt.TextFormat.PlainText)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for label, widget in (
            ("Title", self.title),
            ("Description", self.description),
            ("Structure", self.structure),
        ):
            box = QGroupBox(label)
            inner = QVBoxLayout(box)
            inner.addWidget(widget)
            row = QHBoxLayout()
            button = QPushButton(f"Copy {label}")
            button.clicked.connect(lambda _checked=False, name=label: self.copy(name))
            row.addWidget(button)
            row.addStretch(1)
            if label == "Description":
                row.addWidget(QLabel("Suno's style field"))
            elif label == "Structure":
                row.addWidget(QLabel("Suno's lyrics field"))
            inner.addLayout(row)
            # Only the Structure grows: it is fifteen lines where the other two are
            # one and three, and giving all three the same stretch left two boxes
            # mostly empty and the tags in a scroll bar.
            layout.addWidget(box, 1 if label == "Structure" else 0)
        layout.addWidget(self.problems)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(VALIDATE_DEBOUNCE_MS)
        self._timer.timeout.connect(self.revalidate)
        self._loading = False

    # --- reading and writing the blocks ------------------------------------

    def show_variant(self, variant: PromptVariant | None) -> None:
        """Put a generated variant in the boxes without calling it a hand edit."""
        self._loading = True
        try:
            self.title.setText(variant.title if variant else "")
            self.description.setPlainText(variant.description if variant else "")
            self.structure.setPlainText("\n".join(variant.structure) if variant else "")
            self._instruments = tuple(variant.instruments) if variant else ()
        finally:
            self._loading = False
        self.revalidate()

    def as_variant(self, source: PromptSource = "user") -> PromptVariant:
        """What is in the boxes, as a variant. The instruments come from the last load.

        The instrument list is not parsed back out of the Description: the validator
        needs to know which words were meant as instruments, and re-deriving that from
        the text a person has been editing would be guesswork.
        """
        return PromptVariant(
            title=self.title.text().strip(),
            description=self.description.toPlainText().strip(),
            structure=self.structure_lines(),
            instruments=list(self._instruments),
            source=source,
        )

    def structure_lines(self) -> list[str]:
        return [line for line in self.structure.toPlainText().splitlines() if line.strip()]

    # --- validation --------------------------------------------------------

    def _text_changed(self) -> None:
        if self._loading:
            return
        self._timer.start()
        self.changed.emit()

    def revalidate(self) -> list[Violation]:
        """Run the validator and mark every violated rule on its own line."""
        verdict = validate_prompt(
            self.description.toPlainText().strip(),
            self.structure_lines(),
            self._config,
            self._instruments,
        )
        self.violations = verdict.violations
        self._mark(self.structure, [v for v in self.violations if v.line is not None])
        self._describe()
        return self.violations

    @property
    def ok(self) -> bool:
        return not self.violations

    def _mark(self, editor: QPlainTextEdit, violations: list[Violation]) -> None:
        """Underline the offending lines, with the rule as a tooltip on each."""
        # The type lives on QTextEdit even for a plain text edit, which is where
        # Qt put it and not where it belongs.
        selections: list[QTextEdit.ExtraSelection] = []
        document = editor.document()
        for violation in violations:
            assert violation.line is not None
            block = document.findBlockByNumber(max(violation.line - 1, 0))
            if not block.isValid():
                continue
            fmt = QTextCharFormat()
            fmt.setUnderlineColor(UNDERLINE)
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            fmt.setToolTip(f"{violation.rule}: {violation.detail}")
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = fmt
            selections.append(selection)
        editor.setExtraSelections(selections)

    def _describe(self) -> None:
        if not self.violations:
            self.problems.setText("Valid. Both blocks are ready to paste into Suno.")
            return
        lines = [
            f"line {violation.line}: {violation.rule}, {violation.detail}"
            if violation.line is not None
            else f"{violation.rule}: {violation.detail}"
            for violation in self.violations
        ]
        self.problems.setText("\n".join(lines))

    # --- copying -----------------------------------------------------------

    def copy(self, block: str) -> bool:
        """Put one block on the clipboard. An invalid block asks first.

        Copying something Suno will reject is the one mistake this screen exists to
        prevent, so it is a question and not a refusal: the rules are Suno's and they
        change, and the user may know better than the validator.
        """
        text = {
            "Title": self.title.text().strip(),
            "Description": self.description.toPlainText().strip(),
            "Structure": "\n".join(self.structure_lines()),
        }.get(block, "")
        if not text:
            return False
        if block != "Title" and self.violations and not self._confirm(block):
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:  # pragma: no cover - a platform with no clipboard at all
            return False
        clipboard.setText(text)
        return True

    def _confirm(self, block: str) -> bool:
        reasons = "\n".join(f"  {v.rule}: {v.detail}" for v in self.violations[:5])
        answer = QMessageBox.question(
            self,
            "Copy anyway?",
            f"{block} breaks {len(self.violations)} of Suno's rules:\n{reasons}\n\n"
            "Copy it as it is?",
        )
        return bool(answer == QMessageBox.StandardButton.Yes)

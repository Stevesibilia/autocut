"""The near duplicates, as stacks you can swap.

The selection already decided which clip of a cluster or a place visit is in the edit,
and it is right most of the time and wrong in a way a person spots in a second. This
view puts the pick and the ones it beat side by side so that spotting it is one click,
not a filter, a scroll and two decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autocut.core.manifest import Manifest, Segment
from autocut.gui import theme
from autocut.gui.state import ProjectState

THUMB_HEIGHT = 96

#: A stack of a dozen thumbnails is a row nobody reads. The alternatives are ordered
#: by score, so the ones worth swapping in are the first few.
MAX_ALTERNATIVES = 4


@dataclass(slots=True)
class Group:
    """One cluster or one visit: the clip in the edit, and the ones behind it."""

    key: str
    title: str
    pick: Segment | None
    others: list[Segment] = field(default_factory=list)
    #: "cluster" for a visual stack, "visit" for a place. The summary counts by this
    #: rather than by picking the key apart.
    kind: str = ""

    @property
    def size(self) -> int:
        return len(self.others) + (1 if self.pick is not None else 0)


def groups_summary(manifest: Manifest | None) -> str:
    """The one line the right panel ends with, e.g. `13 stacks · 6 places · 2 held back`.

    A pure function of the manifest so the sentence can be tested without building the
    stacks, and so the panel and the groups view cannot disagree about the count.
    """
    if manifest is None:
        return "No project open."
    groups = build_groups(manifest)
    stacks = sum(1 for group in groups if group.kind == "cluster")
    places = sum(1 for group in groups if group.kind == "visit")
    held = sum(
        1
        for segment in manifest.segments.values()
        if segment.outcome != "selected" and segment.reason == "place_cap"
    )
    if not groups and not held:
        return "No near duplicates yet. Run the selection first."
    parts = [f"{stacks} stacks", f"{places} places"]
    if held:
        parts.append(f"{held} held back by the place cap")
    return " · ".join(parts)


def build_groups(manifest: Manifest) -> list[Group]:
    """Stacks worth showing: visual clusters and place visits with more than one clip.

    A group of one is not a duplicate and has nothing to swap, so it is left out; the
    grid already shows those clips. Clusters come first because visual similarity is
    what the selection actually penalised, and a visit can hold clips of quite
    different subjects that only share a spot.
    """
    groups: list[Group] = []
    for kind, attribute, label in (
        ("cluster", "cluster_id", "Cluster"),
        ("visit", "visit_id", "Visit"),
    ):
        buckets: dict[int, list[Segment]] = {}
        for segment in manifest.segments.values():
            if segment.outcome == "rejected":
                continue
            value = getattr(segment, attribute)
            if value is None:
                continue
            buckets.setdefault(int(value), []).append(segment)
        for value, members in sorted(buckets.items()):
            if len(members) < 2:
                continue
            ordered = sorted(members, key=lambda s: (-(s.score or 0.0), s.id))
            pick = next((s for s in ordered if s.outcome == "selected"), None)
            others = [s for s in ordered if s is not pick]
            groups.append(
                Group(
                    key=f"{kind}:{value}",
                    title=f"{label} {value}, {len(members)} clips",
                    pick=pick,
                    others=others,
                    kind=kind,
                )
            )
    return groups


class GroupCard(QFrame):
    """One stack: the pick on the left, the alternatives after it."""

    swap_requested = Signal(str, str)
    """The clip to keep, and the clip it replaces."""

    def __init__(self, group: Group, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.group = group
        self._state = state

        layout = QVBoxLayout(self)
        header = QLabel(group.title)
        header.setProperty("role", "title")
        layout.addWidget(header)

        row = QHBoxLayout()
        if group.pick is not None:
            row.addWidget(self._thumb(group.pick, chosen=True))
        shown = group.others[:MAX_ALTERNATIVES]
        for other in shown:
            row.addWidget(self._thumb(other, chosen=False))
        hidden = len(group.others) - len(shown)
        if hidden:
            row.addWidget(QLabel(f"and {hidden} more"))
        row.addStretch(1)
        layout.addLayout(row)

    def _thumb(self, segment: Segment, chosen: bool) -> QWidget:
        colors = theme.current().palette
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(2, 2, 2, 2)

        picture = _ClickableLabel(segment.id)
        picture.setFixedHeight(THUMB_HEIGHT)
        pixmap = QPixmap(str(segment.thumbnail)) if segment.thumbnail else QPixmap()
        if pixmap.isNull():
            picture.setText("no thumbnail")
            picture.setStyleSheet(f"background: {colors.surface}; color: {colors.text_muted};")
        else:
            picture.setPixmap(
                pixmap.scaledToHeight(THUMB_HEIGHT, Qt.TransformationMode.SmoothTransformation)
            )
        if chosen:
            picture.setStyleSheet(f"border: 2px solid {colors.accent};")
        elif segment.user_rejected:
            picture.setStyleSheet(f"border: 2px solid {colors.red};")
        picture.clicked.connect(self._clicked)
        column.addWidget(picture)

        score = f"{segment.score:.2f}" if segment.score is not None else "unscored"
        state = "in the edit" if chosen else ("rejected" if segment.user_rejected else "behind")
        column.addWidget(QLabel(f"{score}  {state}"))
        name = QLabel(self.describe(segment))
        name.setToolTip(segment.id)
        column.addWidget(name)
        return holder

    def describe(self, segment: Segment) -> str:
        """The clip's file name and where in it, which is how a person finds a shot.

        ``file_id`` is a content hash: it identifies the file exactly and tells a reader
        nothing. The id is still on the tooltip, for the case where somebody is
        comparing the screen with a manifest.
        """
        manifest = self._state.manifest
        source = manifest.files.get(segment.file_id) if manifest is not None else None
        name = Path(source.path).name if source is not None else segment.file_id[:8]
        start, _ = segment.effective_bounds
        return f"{name}  {start:.1f} s"

    def _clicked(self, segment_id: str) -> None:
        """Clicking a clip behind the pick swaps the two. Clicking the pick does nothing.

        A click on the clip already in the edit is the most likely accident on this
        screen, and rejecting the pick in favour of itself would be a strange thing to
        have to undo.
        """
        pick = self.group.pick
        if pick is None or segment_id == pick.id:
            return
        self.swap_requested.emit(segment_id, pick.id)


class _ClickableLabel(QLabel):
    """A label that reports which segment was clicked."""

    clicked = Signal(str)

    def __init__(self, segment_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segment_id = segment_id
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self.clicked.emit(self._segment_id)


class GroupsView(QScrollArea):
    """Every stack in the project, rebuilt when the selection changes."""

    swap_requested = Signal(str, str)

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setWidgetResizable(True)
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self.setWidget(self._body)
        self.empty = QLabel("No near duplicates to compare yet. Run the selection first.")
        self.empty.setProperty("role", "muted")
        self._layout.addWidget(self.empty)
        self._layout.addStretch(1)
        self.cards: list[GroupCard] = []

    def refresh(self) -> None:
        """Rebuild the stacks. Cheap enough: it is thumbnails and labels, no decoding."""
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        manifest = self._state.manifest
        groups = build_groups(manifest) if manifest is not None else []
        self.empty.setVisible(not groups)
        for index, group in enumerate(groups):
            card = GroupCard(group, self._state, self._body)
            card.swap_requested.connect(self.swap_requested.emit)
            self._layout.insertWidget(index + 1, card)
            self.cards.append(card)

    @property
    def group_count(self) -> int:
        return len(self.cards)

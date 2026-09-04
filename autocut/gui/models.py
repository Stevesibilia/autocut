"""A Qt model over the manifest's segments.

The grids of the Review screen are views onto this, so sorting, filtering and
selection are Qt's own machinery rather than lists the screens copy and forget to
refresh. The model reads the manifest and never writes it: a change goes through
``ProjectState``, which emits ``segments_changed``, which is what brings the model
back in step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeAlias

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from autocut.core.manifest import Manifest, Outcome, Segment
from autocut.gui.state import ProjectState


class SegmentRole:
    """Roles above ``Qt.UserRole``, one per field a view or a proxy needs."""

    SEGMENT_ID = int(Qt.ItemDataRole.UserRole) + 1
    SCORE = int(Qt.ItemDataRole.UserRole) + 2
    OUTCOME = int(Qt.ItemDataRole.UserRole) + 3
    ORDER = int(Qt.ItemDataRole.UserRole) + 4
    DURATION = int(Qt.ItemDataRole.UserRole) + 5
    START = int(Qt.ItemDataRole.UserRole) + 6
    SOURCE_CLASS = int(Qt.ItemDataRole.UserRole) + 7
    DOMINANT_TAG = int(Qt.ItemDataRole.UserRole) + 8
    THUMBNAIL = int(Qt.ItemDataRole.UserRole) + 9
    FILE_NAME = int(Qt.ItemDataRole.UserRole) + 10


#: Qt hands a view's model either kind of index, and an override has to accept both.
AnyIndex: TypeAlias = QModelIndex | QPersistentModelIndex

#: Qt calls ``rowCount`` with no argument to mean the root, and the default has to be
#: an index object. One instance, because an invalid index carries no state.
ROOT = QModelIndex()


def segment_duration(segment: Segment) -> float:
    """The trimmed length, which is what every stage after analysis works with."""
    start = segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
    end = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
    return max(end - start, 0.0)


class SegmentListModel(QAbstractListModel):
    """Every segment of the open project, selected clips first in edit order.

    The order is the report's: what the user will see in CapCut comes first, then the
    rest in capture order, so the two views of one project agree.
    """

    def __init__(self, state: ProjectState, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._ids: list[str] = []
        state.segments_changed.connect(self._reload)
        state.selection_changed.connect(self._reload)
        self._reload()

    @property
    def _manifest(self) -> Manifest | None:
        return self._state.manifest

    def _reload(self, changed: list[str] | None = None) -> None:
        """Rebuild the row order. A full reset, because selection reorders everything.

        Selection is not a per row edit: one clip winning can change the order of every
        other clip and the outcome of its neighbours, so there is no smaller honest
        signal to emit than this one. ``changed`` is accepted and ignored for that
        reason: the ids tell a screen what to highlight, not this model what to skip.
        """
        del changed
        self.beginResetModel()
        manifest = self._manifest
        if manifest is None:
            self._ids = []
        else:
            file_order = {file_id: position for position, file_id in enumerate(manifest.files)}
            self._ids = [
                segment.id
                for segment in sorted(
                    manifest.segments.values(),
                    key=lambda segment: (
                        0 if segment.outcome == "selected" else 1,
                        segment.order if segment.order is not None else 0,
                        file_order.get(segment.file_id, 0),
                        segment.start_s,
                    ),
                )
            ]
        self.endResetModel()

    def rowCount(self, parent: AnyIndex = ROOT) -> int:  # noqa: N802 - Qt override
        if parent.isValid():
            return 0
        return len(self._ids)

    def segment_at(self, row: int) -> Segment | None:
        manifest = self._manifest
        if manifest is None or not 0 <= row < len(self._ids):
            return None
        return manifest.segments.get(self._ids[row])

    def row_of(self, segment_id: str) -> int:
        """The row showing ``segment_id``, or -1. Lets a screen keep its selection."""
        try:
            return self._ids.index(segment_id)
        except ValueError:
            return -1

    def data(  # noqa: C901 - one branch per role, flatter than any dispatch table
        self, index: AnyIndex, role: int = int(Qt.ItemDataRole.DisplayRole)
    ) -> Any:
        segment = self.segment_at(index.row()) if index.isValid() else None
        if segment is None:
            return None
        manifest = self._manifest
        source = manifest.files.get(segment.file_id) if manifest is not None else None
        name = Path(source.path).name if source is not None else segment.file_id

        if role == int(Qt.ItemDataRole.DisplayRole):
            return f"{name}  {segment.start_s:.1f} s"
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return f"{segment.id}\n{segment.reason or segment.outcome}"
        if role == SegmentRole.SEGMENT_ID:
            return segment.id
        if role == SegmentRole.SCORE:
            return segment.score if segment.score is not None else -1.0
        if role == SegmentRole.OUTCOME:
            return segment.outcome
        if role == SegmentRole.ORDER:
            return segment.order if segment.order is not None else 0
        if role == SegmentRole.DURATION:
            return segment_duration(segment)
        if role == SegmentRole.START:
            return segment.start_s
        if role == SegmentRole.SOURCE_CLASS:
            return source.source_class if source is not None else ""
        if role == SegmentRole.DOMINANT_TAG:
            return segment.dominant_tag or ""
        if role == SegmentRole.THUMBNAIL:
            return str(segment.thumbnail) if segment.thumbnail else ""
        if role == SegmentRole.FILE_NAME:
            return name
        return None

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802 - Qt override
        names = super().roleNames()
        for role, name in (
            (SegmentRole.SEGMENT_ID, b"segmentId"),
            (SegmentRole.SCORE, b"score"),
            (SegmentRole.OUTCOME, b"outcome"),
            (SegmentRole.ORDER, b"order"),
            (SegmentRole.DURATION, b"duration"),
            (SegmentRole.SOURCE_CLASS, b"sourceClass"),
            (SegmentRole.DOMINANT_TAG, b"dominantTag"),
        ):
            names[role] = QByteArray(name)
        return names


class SegmentFilterProxy(QSortFilterProxyModel):
    """Outcome, source class and tag filters over the segment list.

    A proxy rather than a second list: the model stays the single description of what
    the project holds, and a screen showing only the rejected clips is a filter setting
    rather than another copy to keep in step.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # ``invalidate`` rather than ``invalidateRowsFilter``: PySide6 6.11 marks the
        # narrower protected calls deprecated, and this model has one column, so there
        # is nothing to save by telling Qt only the rows changed.
        self._outcomes: set[Outcome] = set()
        self._source_classes: set[str] = set()
        self._tag: str = ""
        self.setDynamicSortFilter(True)

    def set_outcomes(self, outcomes: set[Outcome]) -> None:
        """Show only these outcomes. An empty set shows every one of them."""
        self._outcomes = set(outcomes)
        self.invalidate()

    def set_source_classes(self, classes: set[str]) -> None:
        self._source_classes = set(classes)
        self.invalidate()

    def set_tag(self, tag: str) -> None:
        self._tag = tag
        self.invalidate()

    def sort_by(self, role: int, descending: bool = True) -> None:
        self.setSortRole(role)
        self.sort(0, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)

    def filterAcceptsRow(  # noqa: N802 - Qt override
        self, source_row: int, source_parent: AnyIndex
    ) -> bool:
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        if self._outcomes and index.data(SegmentRole.OUTCOME) not in self._outcomes:
            return False
        if self._source_classes and index.data(SegmentRole.SOURCE_CLASS) not in (
            self._source_classes
        ):
            return False
        return not (self._tag and index.data(SegmentRole.DOMINANT_TAG) != self._tag)

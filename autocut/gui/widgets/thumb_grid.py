"""The clip grid: one card per segment, with the markers a reviewer needs at a glance.

A ``QListView`` in icon mode over the shell's segment model, so sorting and filtering
are Qt proxies rather than lists this widget would have to keep in step. The delegate
paints rather than building a widget per card, because a holiday folder is hundreds of
segments and hundreds of widgets is a slow grid and a large amount of memory for
pictures that are already JPEGs.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from autocut.gui.models import AnyIndex, SegmentFilterProxy, SegmentListModel, SegmentRole
from autocut.gui.state import ProjectState
from autocut.gui.widgets.scrubber import StripCache, scaled_frame

#: Room under the picture for two lines of labels.
LABEL_HEIGHT = 42
CARD_MARGIN = 6
BADGE_HEIGHT = 18

#: One colour per state a card can be in. Green for what the reviewer kept, red for
#: what they threw out, blue for the machine's own picks, grey for what the rules
#: rejected: the human decisions are the saturated ones on purpose.
KEPT = QColor(60, 180, 100)
USER_REJECTED = QColor(210, 80, 80)
SELECTED = QColor(70, 140, 230)
RULE_REJECTED = QColor(130, 130, 130)


class ThumbnailCache:
    """Card pictures by segment id, so scrolling does not re-decode JPEGs."""

    def __init__(self) -> None:
        self._pixmaps: dict[str, QPixmap] = {}

    def clear(self) -> None:
        self._pixmaps.clear()

    def pixmap(self, segment_id: str, path: str) -> QPixmap:
        cached = self._pixmaps.get(segment_id)
        if cached is not None:
            return cached
        pixmap = QPixmap(path) if path else QPixmap()
        self._pixmaps[segment_id] = pixmap
        return pixmap


class SegmentCardDelegate(QStyledItemDelegate):
    """Paints one card: the picture, the duration, the score bar and the markers."""

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._thumbs = ThumbnailCache()
        self.hovered_id: str = ""
        self.hovered_fraction: float = 0.0
        self.strips = StripCache(self)

    def clear_caches(self) -> None:
        self._thumbs.clear()
        self.strips.clear()

    def card_size(self) -> QSize:
        width = self._state.config.gui.grid_thumbnail_px
        return QSize(width, int(width * 9 / 16) + LABEL_HEIGHT)

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: AnyIndex
    ) -> QSize:
        return self.card_size()

    def paint(  # noqa: C901 - one branch per marker, flatter than any indirection
        self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex
    ) -> None:
        segment_id = str(index.data(SegmentRole.SEGMENT_ID) or "")
        rect = option.rect.adjusted(CARD_MARGIN, CARD_MARGIN, -CARD_MARGIN, -CARD_MARGIN)
        picture = QRect(rect.x(), rect.y(), rect.width(), rect.height() - LABEL_HEIGHT)
        painter.save()

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())

        pixmap = self._picture(segment_id, index, picture.width(), picture.height())
        if not pixmap.isNull():
            painter.drawPixmap(picture, pixmap)
        else:
            painter.fillRect(picture, QColor(60, 60, 60))
            painter.setPen(QPen(QColor(160, 160, 160)))
            painter.drawText(picture, Qt.AlignmentFlag.AlignCenter, "no thumbnail")

        outcome = str(index.data(SegmentRole.OUTCOME) or "")
        decision = str(index.data(SegmentRole.USER_DECISION) or "")
        order = int(index.data(SegmentRole.ORDER) or 0)
        # A human decision outranks the machine's: it is the one thing on the card that
        # no automatic step is allowed to have changed. Each state gets a border and a
        # badge rather than a line of text under the picture, because the question a
        # reviewer scans the grid for is which clips are in the edit, and a number in a
        # row of numbers does not answer it.
        if decision == "keep":
            self._frame(painter, picture, KEPT, 3)
            self._badge(painter, picture, f"KEPT {order}" if order else "KEPT", KEPT)
        elif decision == "reject":
            self._frame(painter, picture, USER_REJECTED, 3)
            self._badge(painter, picture, "OUT", USER_REJECTED)
        elif outcome == "selected":
            self._frame(painter, picture, SELECTED, 3)
            self._badge(painter, picture, f"IN {order}" if order else "IN", SELECTED)
        elif outcome == "rejected":
            self._frame(painter, picture, RULE_REJECTED, 1)

        painter.setPen(
            QPen(
                option.palette.highlightedText().color()
                if selected
                else option.palette.text().color()
            )
        )
        labels = QRect(rect.x(), picture.bottom() + 2, rect.width(), LABEL_HEIGHT - 2)
        painter.drawText(
            labels,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            self._first_line(index),
        )
        painter.drawText(
            labels,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
            self._second_line(index, decision),
        )
        painter.restore()

    def _picture(self, segment_id: str, index: AnyIndex, width: int, height: int) -> QPixmap:
        """The frame under the pointer while hovering, the thumbnail otherwise."""
        if segment_id and segment_id == self.hovered_id:
            frame = self._hover_frame(segment_id, width, height)
            if frame is not None and not frame.isNull():
                return frame
        thumbnail = self._thumbs.pixmap(segment_id, str(index.data(SegmentRole.THUMBNAIL) or ""))
        if thumbnail.isNull():
            return thumbnail
        return thumbnail.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _hover_frame(self, segment_id: str, width: int, height: int) -> QPixmap | None:
        manifest = self._state.manifest
        segment = self._state.segment(segment_id)
        if manifest is None or segment is None:
            return None
        strip = self.strips.strip(manifest, segment, self._state.config)
        if strip is None:
            return None
        return scaled_frame(strip, self.hovered_fraction, width, height)

    def _first_line(self, index: AnyIndex) -> str:
        duration = float(index.data(SegmentRole.DURATION) or 0.0)
        source_class = str(index.data(SegmentRole.SOURCE_CLASS) or "")
        return f"{duration:.1f} s  {source_class}"

    def _second_line(self, index: AnyIndex, decision: str) -> str:
        """Score, tag and the reason a clip is out. The badge carries the state itself."""
        score = index.data(SegmentRole.SCORE)
        tag = str(index.data(SegmentRole.DOMINANT_TAG) or "")
        parts: list[str] = []
        if score is not None and score >= 0.0:
            parts.append(f"{float(score):.2f}")
        if tag:
            parts.append(tag)
        reason = str(index.data(SegmentRole.REASON) or "")
        if reason and not decision:
            parts.append(reason)
        return "  ".join(parts)

    @staticmethod
    def _frame(painter: QPainter, rect: QRect, color: QColor, width: int) -> None:
        pen = QPen(color)
        pen.setWidth(width)
        painter.setPen(pen)
        painter.drawRect(rect.adjusted(1, 1, -1, -1))

    @staticmethod
    def _badge(painter: QPainter, rect: QRect, text: str, color: QColor) -> None:
        """A filled corner label. On the picture, because that is where the eye is."""
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 12
        box = QRect(rect.x() + 3, rect.y() + 3, width, BADGE_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(box)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)


class ThumbGrid(QListView):
    """The grid itself: hover scrubbing, double click to preview, keys for decisions."""

    activated_segment = Signal(str)
    current_segment_changed = Signal(str)
    keep_requested = Signal(str)
    reject_requested = Signal(str)
    toggle_requested = Signal(str)
    undo_requested = Signal()

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.model_source = SegmentListModel(state, self)
        self.proxy = SegmentFilterProxy(self)
        self.proxy.setSourceModel(self.model_source)
        self.proxy.sort_by_chronology()
        self.setModel(self.proxy)

        self.delegate = SegmentCardDelegate(state, self)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setMouseTracking(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.doubleClicked.connect(self._emit_activated)

        # Every decision re-selects, every re-selection resets the model, and a reset
        # drops the current index. Without this the cursor jumps to the top after each
        # keystroke, which makes working down the grid with the keyboard impossible.
        self._sticky_id = ""
        self.model_source.modelAboutToBeReset.connect(self._remember_current)
        self.model_source.modelReset.connect(self._restore_current)

    # --- what the grid is showing ------------------------------------------

    @property
    def count(self) -> int:
        return self.proxy.rowCount()

    def current_id(self) -> str:
        index = self.currentIndex()
        return str(index.data(SegmentRole.SEGMENT_ID) or "") if index.isValid() else ""

    def select_segment(self, segment_id: str) -> bool:
        """Put the cursor on one segment. False when it is filtered out or gone."""
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(SegmentRole.SEGMENT_ID) == segment_id:
                self.setCurrentIndex(index)
                return True
        return False

    def _remember_current(self) -> None:
        current = self.current_id()
        if current:
            self._sticky_id = current

    def _restore_current(self) -> None:
        """Put the cursor back on the clip it was on, or on the nearest row that exists.

        A clip can leave the grid because of the very decision that moved the cursor,
        which is why the fallback is a row and not an id: the reviewer's place in the
        list survives even when the clip they were looking at does not.
        """
        if not self._sticky_id:
            return
        if self.select_segment(self._sticky_id):
            return
        row = self.model_source.row_of(self._sticky_id)
        if row < 0 and self.proxy.rowCount():
            self.setCurrentIndex(self.proxy.index(0, 0))

    def visible_ids(self) -> list[str]:
        return [
            str(self.proxy.index(row, 0).data(SegmentRole.SEGMENT_ID))
            for row in range(self.proxy.rowCount())
        ]

    # --- hover scrubbing ---------------------------------------------------

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """Follow the pointer across a card and repaint that card only."""
        index = self.indexAt(event.position().toPoint())
        segment_id = str(index.data(SegmentRole.SEGMENT_ID) or "") if index.isValid() else ""
        fraction = self._fraction_in(index, event.position().toPoint()) if index.isValid() else 0.0
        changed = segment_id != self.delegate.hovered_id
        moved = abs(fraction - self.delegate.hovered_fraction) > 0.01
        previous = self.delegate.hovered_id
        self.delegate.hovered_id = segment_id
        self.delegate.hovered_fraction = fraction
        if changed and previous:
            self._repaint(previous)
        if changed or moved:
            self._repaint(segment_id)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        previous = self.delegate.hovered_id
        self.delegate.hovered_id = ""
        if previous:
            self._repaint(previous)
        super().leaveEvent(event)

    def hover(self, segment_id: str, fraction: float) -> None:
        """Scrub a card without a pointer. For tests and for keyboard scrubbing."""
        self.delegate.hovered_id = segment_id
        self.delegate.hovered_fraction = fraction
        self._repaint(segment_id)

    def hovered_frame_index(self) -> int:
        """Which frame of the strip is on screen, or -1 when nothing is being scrubbed."""
        segment_id = self.delegate.hovered_id
        manifest = self._state.manifest
        segment = self._state.segment(segment_id) if segment_id else None
        if manifest is None or segment is None:
            return -1
        strip = self.delegate.strips.strip(manifest, segment, self._state.config)
        if strip is None:
            return -1
        return strip.index_at(self.delegate.hovered_fraction)

    def _fraction_in(self, index: AnyIndex, point: QPoint) -> float:
        rect = self.visualRect(index)
        if rect.width() <= 0:
            return 0.0
        return min(max((point.x() - rect.x()) / rect.width(), 0.0), 1.0)

    def _repaint(self, segment_id: str) -> None:
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(SegmentRole.SEGMENT_ID) == segment_id:
                self.update(index)
                return

    # --- keyboard ----------------------------------------------------------

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        """K keeps, R rejects, space toggles, U undoes. Arrows stay Qt's own.

        Forty clips in two minutes is the goal of SPEC.md section 11, and that only
        works if the hand never leaves the keyboard.
        """
        segment_id = self.current_id()
        key = event.key()
        if key == Qt.Key.Key_K and segment_id:
            self.keep_requested.emit(segment_id)
            return
        if key == Qt.Key.Key_R and segment_id:
            self.reject_requested.emit(segment_id)
            return
        if key == Qt.Key.Key_Space and segment_id:
            self.toggle_requested.emit(segment_id)
            return
        if key == Qt.Key.Key_U:
            self.undo_requested.emit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and segment_id:
            self.activated_segment.emit(segment_id)
            return
        super().keyPressEvent(event)

    def currentChanged(  # noqa: N802 - Qt override
        self, current: AnyIndex, previous: AnyIndex
    ) -> None:
        super().currentChanged(current, previous)
        self.current_segment_changed.emit(
            str(current.data(SegmentRole.SEGMENT_ID) or "") if current.isValid() else ""
        )

    def _emit_activated(self, index: AnyIndex) -> None:
        if index.isValid():
            self.activated_segment.emit(str(index.data(SegmentRole.SEGMENT_ID) or ""))

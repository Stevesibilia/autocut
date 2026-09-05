"""The clip grid: one card per segment, with the markers a reviewer needs at a glance.

A ``QListView`` in icon mode over the shell's segment model, so sorting and filtering
are Qt proxies rather than lists this widget would have to keep in step. The delegate
paints rather than building a widget per card, because a holiday folder is hundreds of
segments and hundreds of widgets is a slow grid and a large amount of memory for
pictures that are already JPEGs.

The card is the one the user approved (`docs/design/review-dark.mockup.html`): a rounded
panel, a picture area tinted by source class while the JPEG is not there, a pill badge
top left saying what the clip is and one top right with its length and beat count, then
the class and score on one line, the tags as chips, and last where and when it was shot
or why it is not in the edit. What that badge says is decided in `card.py`, not here.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from autocut.gui import theme
from autocut.gui.models import (
    AnyIndex,
    SegmentFilterProxy,
    SegmentListModel,
    SegmentRole,
)
from autocut.gui.state import ProjectState
from autocut.gui.widgets.card import CardMarker, card_marker
from autocut.gui.widgets.scrubber import StripCache, scaled_frame

#: The gap between one card and the next. The grid's own spacing is zero so the whole
#: rectangle Qt hands the delegate belongs to the card, which is what lets the accent
#: border sit on the card edge rather than inside it.
CARD_MARGIN = 7

#: Room under the picture: title line, chips, and the where and when line.
LABEL_HEIGHT = 74
#: The inner padding of the text block, and the gap between its lines.
TEXT_PADDING = 10
LINE_GAP = 6

BADGE_HEIGHT = 18
BADGE_PADDING = 7
BADGE_INSET = 8
CHIP_HEIGHT = 16
CHIP_PADDING = 7
CHIP_GAP = 6
MAX_CHIPS = 3

#: How much of a card is left when it is not in the edit.
DIMMED_OPACITY = 0.55

#: Which placeholder colour stands in for a class of camera until its JPEG arrives.
PLACEHOLDER_ROLES = {
    "drone": "thumb_drone",
    "actioncam": "thumb_actioncam",
    "phone": "thumb_phone",
}


def placeholder_role(source_class: str) -> str:
    """The palette role behind a thumbnail that has not loaded, by source class."""
    return PLACEHOLDER_ROLES.get(source_class, "thumb_neutral")


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
    """Paints one card: the picture, its badges, and the three lines under it."""

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
        picture = theme.current().metrics.card_picture_height
        return QSize(width + CARD_MARGIN * 2, picture + LABEL_HEIGHT + CARD_MARGIN * 2)

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: AnyIndex
    ) -> QSize:
        return self.card_size()

    def marker(self, index: AnyIndex) -> CardMarker:
        """What this card says, read off the model and decided in `card.py`."""
        similarity = float(index.data(SegmentRole.SIMILARITY) or 0.0)
        lost_to = index.data(SegmentRole.LOST_TO_ORDER)
        return card_marker(
            outcome=str(index.data(SegmentRole.OUTCOME) or ""),
            decision=str(index.data(SegmentRole.USER_DECISION) or ""),
            order=int(index.data(SegmentRole.ORDER) or 0),
            reason=str(index.data(SegmentRole.REASON) or ""),
            place=str(index.data(SegmentRole.PLACE_NAME) or ""),
            clock=str(index.data(SegmentRole.CLOCK) or ""),
            hero=bool(index.data(SegmentRole.HERO)),
            lost_to_order=int(lost_to) if lost_to is not None else None,
            similarity=similarity or None,
        )

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        colors = theme.current().palette
        metrics = theme.current().metrics
        marker = self.marker(index)
        segment_id = str(index.data(SegmentRole.SEGMENT_ID) or "")

        card = option.rect.adjusted(CARD_MARGIN, CARD_MARGIN, -CARD_MARGIN, -CARD_MARGIN)
        picture = QRect(card.x(), card.y(), card.width(), metrics.card_picture_height)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if marker.dimmed:
            painter.setOpacity(DIMMED_OPACITY)

        self._panel(painter, card, colors, metrics, option, marker)
        painter.save()
        self._clip_to_picture(painter, card, picture, metrics)
        self._picture(painter, picture, segment_id, index, colors)
        painter.restore()
        self._badges(painter, picture, index, colors, metrics, marker)
        self._text(painter, card, picture, index, colors, metrics, marker)
        painter.restore()

    # --- the pieces of a card ----------------------------------------------

    def _panel(
        self,
        painter: QPainter,
        card: QRect,
        colors: theme.Palette,
        metrics: theme.Metrics,
        option: QStyleOptionViewItem,
        marker: CardMarker,
    ) -> None:
        """The rounded panel, and the border that says whether this card is current."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(colors.surface))
        painter.drawRoundedRect(card, metrics.radius_card, metrics.radius_card)

        current = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if current:
            colour, width = colors.accent, 2
        elif marker.tone in ("amber", "red"):
            colour, width = getattr(colors, marker.tone), 1
        elif hovered:
            colour, width = colors.border_muted, 1
        else:
            colour, width = colors.border_strong, 1
        pen = QPen(theme.qcolor(colour))
        pen.setWidth(width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = width / 2.0
        painter.drawRoundedRect(
            QRectF(card).adjusted(inset, inset, -inset, -inset),
            metrics.radius_card,
            metrics.radius_card,
        )

    def _clip_to_picture(
        self, painter: QPainter, card: QRect, picture: QRect, metrics: theme.Metrics
    ) -> None:
        """Round the picture's top corners with the card and leave the bottom square."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(card), metrics.radius_card, metrics.radius_card)
        square = QPainterPath()
        square.addRect(QRectF(picture).adjusted(0, metrics.radius_card, 0, 0))
        painter.setClipPath(path.united(square).intersected(_rect_path(picture)))

    def _picture(
        self,
        painter: QPainter,
        picture: QRect,
        segment_id: str,
        index: AnyIndex,
        colors: theme.Palette,
    ) -> None:
        """The frame, or the class tint that stands in for it."""
        source_class = str(index.data(SegmentRole.SOURCE_CLASS) or "")
        painter.fillRect(picture, theme.qcolor(getattr(colors, placeholder_role(source_class))))
        pixmap = self._pixmap(segment_id, index, picture.width(), picture.height())
        if not pixmap.isNull():
            painter.drawPixmap(picture, pixmap)

    def _badges(
        self,
        painter: QPainter,
        picture: QRect,
        index: AnyIndex,
        colors: theme.Palette,
        metrics: theme.Metrics,
        marker: CardMarker,
    ) -> None:
        """The state badge on the left, the length on the right, hero under the state."""
        painter.setFont(theme.font(metrics.label_size, mono=True, weight=theme.STRONG))
        left = self._badge(
            painter,
            QPoint(picture.left() + BADGE_INSET, picture.top() + BADGE_INSET),
            marker.badge,
            theme.qcolor(getattr(colors, marker.tone)),
            theme.qcolor(colors.on_accent if marker.tone != "border_muted" else colors.text),
            metrics,
        )
        if marker.hero:
            self._badge(
                painter,
                QPoint(picture.left() + BADGE_INSET, left.bottom() + 4),
                "hero",
                theme.qcolor(colors.amber),
                theme.qcolor(colors.on_accent),
                metrics,
            )

        painter.setFont(theme.font(metrics.label_size, mono=True))
        length = self._length_text(index)
        width = painter.fontMetrics().horizontalAdvance(length) + BADGE_PADDING * 2
        self._badge(
            painter,
            QPoint(picture.right() - BADGE_INSET - width, picture.top() + BADGE_INSET),
            length,
            theme.qcolor(colors.badge_scrim),
            theme.qcolor(colors.text),
            metrics,
        )

    def _text(
        self,
        painter: QPainter,
        card: QRect,
        picture: QRect,
        index: AnyIndex,
        colors: theme.Palette,
        metrics: theme.Metrics,
        marker: CardMarker,
    ) -> None:
        """Class and score, the tag chips, and where and when or why it lost."""
        left = card.left() + TEXT_PADDING
        right = card.right() - TEXT_PADDING
        width = right - left
        y = picture.bottom() + TEXT_PADDING

        title_height = metrics.title_size + 4
        painter.setFont(theme.font(metrics.title_size, weight=theme.MEDIUM))
        painter.setPen(QPen(theme.qcolor(colors.text)))
        painter.drawText(
            QRect(left, y, width, title_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            str(index.data(SegmentRole.SOURCE_CLASS) or ""),
        )
        score = index.data(SegmentRole.SCORE)
        if score is not None and float(score) >= 0.0:
            painter.setFont(theme.font(metrics.body_size, mono=True))
            painter.setPen(QPen(theme.qcolor(colors.text_muted)))
            painter.drawText(
                QRect(left, y, width, title_height),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{float(score):.2f}",
            )

        y += title_height + LINE_GAP
        self._chips(painter, QPoint(left, y), right, index, colors, metrics)

        y += CHIP_HEIGHT + LINE_GAP
        painter.setFont(theme.font(metrics.label_size))
        painter.setPen(QPen(theme.qcolor(colors.text_muted)))
        detail = painter.fontMetrics().elidedText(marker.detail, Qt.TextElideMode.ElideRight, width)
        painter.drawText(
            QRect(left, y, width, metrics.label_size + 4),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            detail,
        )

    def _chips(
        self,
        painter: QPainter,
        start: QPoint,
        right: int,
        index: AnyIndex,
        colors: theme.Palette,
        metrics: theme.Metrics,
    ) -> None:
        """The clip's tags, as many as fit, in the order the analysis ranked them."""
        tags = list(index.data(SegmentRole.TAGS) or [])[:MAX_CHIPS]
        painter.setFont(theme.font(metrics.label_size))
        x = start.x()
        for tag in tags:
            width = painter.fontMetrics().horizontalAdvance(str(tag)) + CHIP_PADDING * 2
            if x + width > right:
                return
            box = QRect(x, start.y(), width, CHIP_HEIGHT)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(colors.surface_raised))
            painter.drawRoundedRect(box, CHIP_HEIGHT // 2, CHIP_HEIGHT // 2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.qcolor(colors.text_secondary)))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), str(tag))
            x += width + CHIP_GAP

    @staticmethod
    def _badge(
        painter: QPainter,
        at: QPoint,
        text: str,
        fill: QColor,
        ink: QColor,
        metrics: theme.Metrics,
    ) -> QRect:
        """A filled pill over the picture. Returns its rectangle, so one can sit below."""
        width = painter.fontMetrics().horizontalAdvance(text) + BADGE_PADDING * 2
        box = QRect(at.x(), at.y(), width, BADGE_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(box, metrics.radius_badge, metrics.radius_badge)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ink))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        return box

    @staticmethod
    def _length_text(index: AnyIndex) -> str:
        """`4.0 s` on its own, or `4.0 s · 8♪` once the edit has been synced."""
        duration = float(index.data(SegmentRole.DURATION) or 0.0)
        beats = int(index.data(SegmentRole.BEATS) or 0)
        return f"{duration:.1f} s · {beats}♪" if beats else f"{duration:.1f} s"

    # --- pictures ----------------------------------------------------------

    def _pixmap(self, segment_id: str, index: AnyIndex, width: int, height: int) -> QPixmap:
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


def _rect_path(rect: QRect) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRectF(rect))
    return path


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
        # The card carries its own margin, so the view adds none: the accent border has
        # to sit on the card's edge, and a view spacing would push it inward instead.
        self.setSpacing(0)
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

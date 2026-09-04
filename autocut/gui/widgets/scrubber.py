"""Scrubbing a segment by moving the pointer across its sprite strip.

Hover scrubbing on a 4K original is not attempted (SPEC.md section 6.2). The strip
written by analysis is a row of the frames the analysis already sampled, so scrubbing
is arithmetic on one JPEG: no decoder, no seeking, and the same picture the metrics
were computed from.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt
from PySide6.QtGui import QPixmap

from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Segment
from autocut.core.thumbs import sprite_for_segment


class SpriteStrip:
    """One segment's strip, sliced into frames.

    The frame count comes from the geometry rather than from the manifest: the strip
    is square frames laid side by side, so its width over its height is how many
    there are, and that stays true for a strip built with any ``sprite_max_frames``.
    """

    __slots__ = ("pixmap", "frame_width")

    def __init__(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap
        height = max(pixmap.height(), 1)
        # A strip of one frame is as wide as it is tall in the worst case, so the
        # width is clamped to at least the height to keep the count sane.
        self.frame_width = max(min(height, pixmap.width()), 1)

    @property
    def count(self) -> int:
        if self.pixmap.isNull():
            return 0
        return max(self.pixmap.width() // self.frame_width, 1)

    def index_at(self, fraction: float) -> int:
        """Which frame a position from 0 to 1 across the card lands on."""
        if self.count <= 0:
            return 0
        clamped = min(max(fraction, 0.0), 1.0)
        return min(int(clamped * self.count), self.count - 1)

    def frame(self, index: int) -> QPixmap:
        """One frame as its own pixmap. An empty strip gives an empty pixmap."""
        if self.pixmap.isNull() or self.count <= 0:
            return QPixmap()
        index = min(max(index, 0), self.count - 1)
        rect = QRect(index * self.frame_width, 0, self.frame_width, self.pixmap.height())
        return self.pixmap.copy(rect)

    def frame_at(self, fraction: float) -> QPixmap:
        return self.frame(self.index_at(fraction))


class StripCache(QObject):
    """Strips by segment id, built on first use and kept for the session.

    Decoding one JPEG per card on every mouse move would make the grid feel worse than
    no scrubbing at all, and the strips are a few tens of kilobytes each. A segment
    with no strip is remembered as such, so a project analysed without sprites is not
    asked for the same missing file on every pointer move.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._strips: dict[str, SpriteStrip | None] = {}

    def clear(self) -> None:
        self._strips.clear()

    def forget(self, segment_id: str) -> None:
        self._strips.pop(segment_id, None)

    def strip(
        self, manifest: Manifest, segment: Segment, config: AutocutConfig
    ) -> SpriteStrip | None:
        """This segment's strip, building it from the cache the first time.

        Returns ``None`` when the file was analysed without sprites, in which case
        there is nothing in the cache to build one from and the card keeps its
        thumbnail. The build itself is a NumPy slice and a JPEG write, which is why it
        is affordable on a hover rather than up front for hundreds of segments.
        """
        cached = self._strips.get(segment.id, "missing")
        if cached != "missing":
            return cached  # type: ignore[return-value]
        path = sprite_for_segment(manifest, segment, config)
        strip = _load(path)
        self._strips[segment.id] = strip
        return strip


def _load(path: Path | None) -> SpriteStrip | None:
    if path is None:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return SpriteStrip(pixmap)


def scaled_frame(strip: SpriteStrip, fraction: float, width: int, height: int) -> QPixmap:
    """The frame under the pointer, scaled to fill a card of this size."""
    frame = strip.frame_at(fraction)
    if frame.isNull():
        return frame
    return frame.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )

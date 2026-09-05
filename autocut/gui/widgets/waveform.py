"""The track, drawn, with the beats the tracker found on top of it.

The point of the picture is not the picture: it is being able to see at a glance that
the beats line up with what the music is doing, because a beat grid that is subtly
wrong produces an edit that feels wrong for reasons nobody can name. Ticks over an
envelope answer that in one look.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from autocut.core.beatsync import envelope
from autocut.gui import theme

#: Cached beside the manifest, keyed by the audio file's size and modification time:
#: decoding a three minute track is a second, and it happens on every screen open.
ENVELOPE_DIRNAME = "waveforms"
ENVELOPE_POINTS = 2000


def envelope_path(output_dir: Path, audio: Path) -> Path:
    """Where this track's envelope is cached for this project.

    The key is the file's size and modification time rather than its content: hashing
    a hundred megabytes to avoid decoding it is not a saving, and a track that was
    replaced under the same name has a different mtime.
    """
    try:
        stat = audio.stat()
        stamp = f"{stat.st_size}-{int(stat.st_mtime)}"
    except OSError:
        stamp = "unknown"
    safe = audio.stem.replace("/", "_")[:60]
    return output_dir / ENVELOPE_DIRNAME / f"{safe}-{stamp}.npy"


def load_or_build_envelope(
    samples: np.ndarray, output_dir: Path, audio: Path, points: int = ENVELOPE_POINTS
) -> np.ndarray:
    """The cached envelope for this track, computed and written if it is not there."""
    path = envelope_path(output_dir, audio)
    if path.exists():
        try:
            cached = np.load(path)
        except (OSError, ValueError):
            cached = None
        if cached is not None and cached.ndim == 2 and cached.shape[1] == 2:
            return np.asarray(cached, dtype=np.float32)
    pairs = envelope(samples, points)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A read only project folder costs a cache, not the waveform.
    with contextlib.suppress(OSError):
        np.save(path, pairs)
    return pairs


class WaveformView(QWidget):
    """An envelope with beat ticks. Clicking reports the time under the pointer."""

    clicked_time = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._pairs: np.ndarray = np.zeros((0, 2), dtype=np.float32)
        self._beats: list[float] = []
        self._duration = 0.0
        self._cursor: float | None = None

    def set_track(self, pairs: np.ndarray, beats: list[float], duration_s: float) -> None:
        self._pairs = pairs
        self._beats = list(beats)
        self._duration = max(duration_s, 0.0)
        self._cursor = None
        self.update()

    def clear(self) -> None:
        self.set_track(np.zeros((0, 2), dtype=np.float32), [], 0.0)

    @property
    def beat_count(self) -> int:
        return len(self._beats)

    def set_cursor(self, seconds: float | None) -> None:
        self._cursor = seconds
        self.update()

    def time_at(self, x: int) -> float:
        if self.width() <= 0 or self._duration <= 0:
            return 0.0
        return min(max(x / self.width() * self._duration, 0.0), self._duration)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        seconds = self.time_at(int(event.position().x()))
        self.set_cursor(seconds)
        self.clicked_time.emit(seconds)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        colors = theme.current().palette
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.qcolor(colors.surface))
        width, height = self.width(), self.height()
        middle = height / 2.0

        if self._pairs.size == 0:
            painter.setPen(QPen(theme.qcolor(colors.text_muted)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no track loaded")
            return

        painter.setPen(QPen(theme.qcolor(colors.accent_muted)))
        count = int(self._pairs.shape[0])
        # One line per pixel column, taking the loudest and quietest of the pairs that
        # fall in it, so a wide widget and a narrow one draw the same shape.
        for column in range(width):
            first = int(column / width * count)
            last = max(int((column + 1) / width * count), first + 1)
            slice_ = self._pairs[first:last]
            if slice_.size == 0:
                continue
            low = float(slice_[:, 0].min()) * middle
            high = float(slice_[:, 1].max()) * middle
            painter.drawLine(
                QPointF(float(column), middle - high), QPointF(float(column), middle - low)
            )

        if self._duration > 0 and self._beats:
            pen = QPen(theme.qcolor(colors.amber))
            pen.setWidth(1)
            painter.setPen(pen)
            for beat in self._beats:
                tick = beat / self._duration * width
                painter.drawLine(QPointF(tick, height * 0.82), QPointF(tick, float(height)))

        if self._cursor is not None and self._duration > 0:
            pen = QPen(theme.qcolor(colors.text))
            pen.setWidth(2)
            painter.setPen(pen)
            cursor = self._cursor / self._duration * width
            painter.drawLine(QPointF(cursor, 0.0), QPointF(cursor, float(height)))

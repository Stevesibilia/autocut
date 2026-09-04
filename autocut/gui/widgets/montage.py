"""Playing the montage, with the cuts marked on a timeline.

The point of watching the montage is the cuts, so the timeline draws one line per
clip boundary and the player says which clip is on screen. Everything about which
clip is where comes from ``montage.json``, which the render wrote from the durations
ffmpeg actually produced, rather than from the durations the edit asked for: a
timeline that disagreed with the file would put the highlight on the wrong card.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from autocut.core.montage import Part, clip_at, read_index

if TYPE_CHECKING:  # pragma: no cover - for the annotations only
    from PySide6.QtMultimedia import QMediaPlayer

BOUNDARY = QColor(230, 170, 60)
PLAYED = QColor(70, 140, 230)
TRACK_BED = QColor(45, 48, 54)
CURRENT = QColor(240, 240, 240)

TIMELINE_HEIGHT = 34


class MontageTimeline(QWidget):
    """The montage as a bar, with a tick at every cut. Clicking one seeks to it."""

    clip_clicked = Signal(int)
    """The order of the clip whose boundary was clicked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(TIMELINE_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._parts: list[Part] = []
        self._duration = 0.0
        self._position = 0.0

    def set_parts(self, parts: list[Part], duration_s: float = 0.0) -> None:
        self._parts = list(parts)
        self._duration = duration_s or (parts[-1].end_s if parts else 0.0)
        self._position = 0.0
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        self.update()

    @property
    def parts(self) -> list[Part]:
        return list(self._parts)

    @property
    def duration_s(self) -> float:
        return self._duration

    def clip_at_x(self, x: int) -> Part | None:
        """Which clip a pixel belongs to. This is what a click means on this widget."""
        if self._duration <= 0 or self.width() <= 0:
            return None
        return clip_at(self._parts, x / self.width() * self._duration)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        part = self.clip_at_x(int(event.position().x()))
        if part is not None:
            self.clip_clicked.emit(part.order)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), TRACK_BED)
        width, height = self.width(), self.height()
        if self._duration <= 0 or not self._parts:
            painter.setPen(QPen(QColor(150, 150, 150)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no montage yet")
            return

        played = min(max(self._position / self._duration, 0.0), 1.0) * width
        painter.fillRect(0, 0, int(played), height, PLAYED)

        pen = QPen(BOUNDARY)
        pen.setWidth(1)
        painter.setPen(pen)
        for part in self._parts[1:]:
            x = part.start_s / self._duration * width
            painter.drawLine(QPointF(x, 0.0), QPointF(x, float(height)))

        current = clip_at(self._parts, self._position)
        if current is not None:
            pen = QPen(CURRENT)
            pen.setWidth(2)
            painter.setPen(pen)
            left = current.start_s / self._duration * width
            right = current.end_s / self._duration * width
            painter.drawRect(QRectF(left, 1.0, right - left, height - 3.0))
            # No label here: the transport row already names the clip, and a centred
            # string over the boundary boxes collided with them.


class MontagePlayer(QWidget):
    """The montage in a video widget, with transport and the timeline under it.

    One widget for both screens: the Review screen watches the edit, the Soundtrack
    screen watches it with the track, and there is no difference between the two
    beyond which file was rendered.
    """

    clip_changed = Signal(str)
    """Segment id of the clip now on screen, so a grid can follow along."""

    boundary_clicked = Signal(str)
    """Segment id of a clip whose boundary was clicked on the timeline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parts: list[Part] = []
        self._path: Path | None = None
        self._player: QMediaPlayer | None = None
        self._audio: Any | None = None
        self._current_order = 0

        self.placeholder = QLabel("Press Play all to build and watch the edit.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setMinimumHeight(200)
        self.placeholder.setStyleSheet("background: #222; color: #999;")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.placeholder)
        self.video: QWidget | None = None

        self.timeline = MontageTimeline()
        self.timeline.clip_clicked.connect(self.seek_to_clip)

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle)
        self.restart_button = QPushButton("From the start")
        self.restart_button.clicked.connect(self.restart)
        self.sound_box = QCheckBox("Sound")
        self.sound_box.toggled.connect(self._sound_toggled)
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)

        transport = QHBoxLayout()
        transport.addWidget(self.play_button)
        transport.addWidget(self.restart_button)
        transport.addWidget(self.sound_box)
        transport.addStretch(1)
        transport.addWidget(self.status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.timeline)
        layout.addLayout(transport)
        self._set_enabled(False)

    # --- what is loaded ----------------------------------------------------

    @property
    def parts(self) -> list[Part]:
        return list(self._parts)

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def current_order(self) -> int:
        return self._current_order

    def current_segment_id(self) -> str:
        part = clip_at(self._parts, self.position_s())
        return part.segment_id if part is not None else ""

    def load(self, montage: Path, index: Path | None = None, sound: bool = False) -> bool:
        """Point the player at a rendered montage. False when the file is not there."""
        montage = Path(montage)
        if not montage.exists():
            self.status.setText(f"{montage.name} is not there any more.")
            return False
        self._path = montage
        self._parts = read_index(index) if index is not None else []
        self.timeline.set_parts(self._parts)
        player = self._build_player(None)
        if player is None:
            return False
        self.sound_box.setChecked(sound)
        player.setSource(QUrl.fromLocalFile(str(montage)))
        self._set_enabled(True)
        self.status.setText(
            f"{len(self._parts)} clips, {self.timeline.duration_s:.1f} s"
            if self._parts
            else montage.name
        )
        return True

    def clear(self) -> None:
        """Forget the montage, which is what a changed edit means."""
        self.stop()
        self._parts = []
        self._path = None
        self.timeline.set_parts([])
        self.stack.setCurrentWidget(self.placeholder)
        self._set_enabled(False)

    def _set_enabled(self, on: bool) -> None:
        for widget in (self.play_button, self.restart_button, self.timeline):
            widget.setEnabled(on)

    # --- the player --------------------------------------------------------

    def _build_player(self, video_output: Any | None) -> QMediaPlayer | None:
        """The player with its outputs attached, built on first use.

        Attached before any source is set, for the reason issue 38 recorded: a player
        with no video output decodes every frame, throws it away and reports nothing.
        """
        if self._player is not None:
            if video_output is not None:
                self._player.setVideoOutput(video_output)
            return self._player
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except ImportError:
            self.status.setText("This build has no Qt multimedia, so the montage cannot play.")
            return None

        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        audio.setMuted(not self.sound_box.isChecked())
        player.setAudioOutput(audio)
        self._audio = audio
        if video_output is None:
            video = QVideoWidget()
            video.setMinimumHeight(200)
            self.video = video
            self.stack.addWidget(video)
            self.stack.setCurrentWidget(video)
            video_output = video
        player.setVideoOutput(video_output)
        player.positionChanged.connect(self._position_changed)
        player.playbackStateChanged.connect(self._state_changed)
        player.mediaStatusChanged.connect(self._media_status_changed)
        player.errorOccurred.connect(self._failed)
        self._player = player
        return player

    def set_video_output(self, output: Any) -> None:
        """Send the frames somewhere else. For a test that wants to count them."""
        self._build_player(output)

    def play(self) -> bool:
        player = self._player
        if player is None or self._path is None:
            return False
        if self.video is not None:
            self.stack.setCurrentWidget(self.video)
        player.play()
        return True

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def toggle(self) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def restart(self) -> None:
        """Back to the first clip, playing. The transport's own Play resumes in place."""
        if self._player is not None:
            self._player.setPosition(0)
            self._current_order = 0
            self.play()

    def position_s(self) -> float:
        return (self._player.position() / 1000.0) if self._player is not None else 0.0

    def seek_to_clip(self, order: int) -> bool:
        """Jump to one clip and play from there. This is what clicking a boundary does.

        Playing rather than showing a still: a click on a boundary means "show me this
        clip", and a paused player cannot be seeked to a frame it has not decoded, so
        the alternative is a blank rectangle. Whoever wanted a still can press Pause.
        """
        part = next((item for item in self._parts if item.order == order), None)
        if part is None or self._player is None:
            return False
        # A hair inside the clip rather than exactly on its edge: seeking to the
        # boundary can land on the last frame of the clip before it.
        self._player.setPosition(int(part.start_s * 1000) + 1)
        self._announce(part)
        self.boundary_clicked.emit(part.segment_id)
        self.play()
        return True

    def _position_changed(self, position_ms: int) -> None:
        seconds = position_ms / 1000.0
        self.timeline.set_position(seconds)
        part = clip_at(self._parts, seconds)
        if part is not None and part.order != self._current_order:
            self._announce(part)

    def _announce(self, part: Part) -> None:
        self._current_order = part.order
        self.status.setText(f"clip {part.order} of {len(self._parts)}  {part.segment_id}")
        self.clip_changed.emit(part.segment_id)

    def _state_changed(self, state: Any) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("Pause" if playing else "Play")

    def _media_status_changed(self, status: Any) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.stack.setCurrentWidget(self.placeholder)
            self.status.setText("The montage would not open. Build it again.")
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.status.setText("End of the edit.")

    def _failed(self, error: Any, message: str = "") -> None:
        del error
        self.stack.setCurrentWidget(self.placeholder)
        self.status.setText(f"Playback failed: {message or 'the platform would not open it'}.")

    def _sound_toggled(self, on: bool) -> None:
        if self._audio is not None:
            self._audio.setMuted(not on)

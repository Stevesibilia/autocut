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

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QPainter, QPaintEvent, QPen, QShortcut
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

from autocut.core.manifest import Manifest
from autocut.core.montage import Part, clip_at, read_index
from autocut.gui import theme
from autocut.gui.widgets.video import checked_video_output

if TYPE_CHECKING:  # pragma: no cover - for the annotations only
    from PySide6.QtMultimedia import QMediaPlayer

#: The strip is the same object on the Review and the Soundtrack screens, and the same
#: language as the montage blocks in the mockup: one rounded block per clip, a two pixel
#: gap between them, played blocks in the muted accent and the one playing in the accent.
BLOCK_RADIUS = 3

#: What the keyboard does while the montage plays, in the order a reviewer learns them.
KEY_HINTS = (
    ("K", "keep"),
    ("R", "reject"),
    ("space", "toggle"),
    ("U", "undo"),
    ("↵", "open clip"),
)


def counter_label(elapsed_s: float, total_s: float) -> str:
    """`0:18.4 / 1:13.6`, the montage's position against its length."""
    return f"{_clock(elapsed_s)} / {_clock(total_s)}"


def _clock(seconds: float) -> str:
    minutes, rest = divmod(max(seconds, 0.0), 60.0)
    return f"{int(minutes)}:{rest:04.1f}"


def clip_labels(manifest: Manifest | None) -> dict[str, str]:
    """A readable name per segment id: the file and where in it the clip starts.

    ``segment_id`` carries a content hash, which identifies the clip exactly and tells
    a reader nothing, so the transport says what the groups view says. Built by the
    screens and handed to the player, which has no manifest of its own.
    """
    if manifest is None:
        return {}
    labels: dict[str, str] = {}
    for segment in manifest.segments.values():
        source = manifest.files.get(segment.file_id)
        name = Path(source.path).name if source is not None else segment.file_id[:8]
        start, _end = segment.effective_bounds
        labels[segment.id] = f"{name}  {start:.1f} s"
    return labels


class MontageTimeline(QWidget):
    """The montage as a bar, with a tick at every cut. Clicking one seeks to it."""

    clip_clicked = Signal(int)
    """The order of the clip whose boundary was clicked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(theme.current().metrics.strip_height)
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
        """One rounded block per clip, with a gap between them instead of a boundary line.

        The gaps are what say where the cuts are, so nothing has to be drawn over the
        blocks: a strip of separate objects reads as a sequence of clips, which is what
        it is, where a filled bar with ticks on it read as one long thing.
        """
        del event
        colors = theme.current().palette
        metrics = theme.current().metrics
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bed = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(colors.track_bed))
        painter.drawRoundedRect(bed, metrics.radius_badge, metrics.radius_badge)

        if self._duration <= 0 or not self._parts:
            painter.setPen(QPen(theme.qcolor(colors.text_muted)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no montage yet")
            return

        pad = float(metrics.strip_padding)
        gap = float(metrics.strip_gap)
        inner = max(self.width() - pad * 2, 1.0)
        height = max(self.height() - pad * 2, 1.0)
        current = clip_at(self._parts, self._position)

        painter.setPen(Qt.PenStyle.NoPen)
        for part in self._parts:
            left = pad + part.start_s / self._duration * inner
            right = pad + part.end_s / self._duration * inner
            width = max(right - left - gap, 1.0)
            if part is current:
                colour = colors.accent
            elif part.end_s <= self._position:
                colour = colors.accent_muted
            else:
                colour = colors.upcoming
            painter.setBrush(theme.qcolor(colour))
            painter.drawRoundedRect(QRectF(left, pad, width, height), BLOCK_RADIUS, BLOCK_RADIUS)


def _key_hints(metrics: theme.Metrics) -> QWidget:
    """The row under the strip saying what the keyboard does while the montage plays."""
    colors = theme.current().palette
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(metrics.space * 2)
    for key, meaning in KEY_HINTS:
        pair = QWidget()
        inner = QHBoxLayout(pair)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(6)
        stroke = QLabel(key)
        stroke.setFont(theme.font(metrics.body_size, mono=True))
        stroke.setStyleSheet(f"color: {colors.text_secondary};")
        meaning_label = QLabel(meaning)
        meaning_label.setProperty("role", "muted")
        inner.addWidget(stroke)
        inner.addWidget(meaning_label)
        row.addWidget(pair)
    row.addStretch(1)
    return holder


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

    back_requested = Signal()
    """The user wants the grid back: the button, or Escape while this has focus."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parts: list[Part] = []
        self._path: Path | None = None
        self._labels: dict[str, str] = {}
        self._player: QMediaPlayer | None = None
        self._audio: Any | None = None
        self._current_order = 0

        self.placeholder = QLabel("Press Play all to build and watch the edit.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setMinimumHeight(200)
        placeholder_colors = theme.current().palette
        self.placeholder.setStyleSheet(
            f"background: {placeholder_colors.surface}; color: {placeholder_colors.text_muted};"
        )
        self.stack = QStackedWidget()
        self.stack.addWidget(self.placeholder)
        self.video: QWidget | None = None

        self.timeline = MontageTimeline()
        self.timeline.clip_clicked.connect(self.seek_to_clip)

        # Scoped to this widget, so it competes with nothing elsewhere in the window.
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape.activated.connect(self.back_requested.emit)

        metrics = theme.current().metrics
        self.play_button = QPushButton("Play")
        self.play_button.setProperty("variant", "primary")
        self.play_button.clicked.connect(self.toggle)
        self.restart_button = QPushButton("From the start")
        self.restart_button.clicked.connect(self.restart)
        # The way out. Without it Play all replaced the grid and nothing brought it
        # back, which is what the Mac found: the tiles were simply gone.
        self.back_button = QPushButton("Back to clips")
        self.back_button.clicked.connect(self.back_requested.emit)
        self.sound_box = QCheckBox("Sound")
        self.sound_box.toggled.connect(self._sound_toggled)

        # Which clip is on screen and where it came from, above the strip, so the
        # blocks below never have to carry a label of their own.
        self.clip_line = QLabel("")
        self.clip_line.setTextFormat(Qt.TextFormat.PlainText)
        self.elapsed = QLabel("")
        self.elapsed.setFont(theme.font(metrics.body_size, mono=True))
        self.elapsed.setProperty("role", "muted")

        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setProperty("role", "muted")

        transport = QHBoxLayout()
        transport.setSpacing(metrics.space + 4)
        transport.addWidget(self.play_button)
        transport.addWidget(self.restart_button)
        transport.addWidget(self.back_button)
        transport.addWidget(self.clip_line, 1)
        transport.addWidget(self.elapsed)
        transport.addWidget(self.sound_box)

        # The strip and its key hints live in one widget so a screen can take the whole
        # thing and put it somewhere else. The Review screen does: the strip belongs
        # under the grid, where it says what the edit looks like before anything plays.
        self.strip = QWidget()
        strip_layout = QVBoxLayout(self.strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(metrics.space)
        strip_layout.addWidget(self.timeline)
        strip_layout.addWidget(_key_hints(metrics))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.space)
        layout.addWidget(self.stack, 1)
        layout.addLayout(transport)
        layout.addWidget(self.strip)
        layout.addWidget(self.status)
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
        """Which clip the player is on, by the last clip it was told to show.

        `_current_order` rather than the position alone: a seek sets the position
        asynchronously, so asking straight after clicking a boundary or jumping to a
        clip returned whatever was playing before. The position is the fallback for a
        player that has moved on its own.
        """
        part = next((item for item in self._parts if item.order == self._current_order), None)
        if part is None:
            part = clip_at(self._parts, self.position_s())
        return part.segment_id if part is not None else ""

    def load(
        self,
        montage: Path,
        index: Path | None = None,
        sound: bool = False,
        labels: dict[str, str] | None = None,
    ) -> bool:
        """Point the player at a rendered montage. False when the file is not there.

        ``labels`` names the clips for the transport. Without it the transport falls
        back to the segment id, which is a hash and is better than nothing only just.
        """
        montage = Path(montage)
        if not montage.exists():
            self.status.setText(f"{montage.name} is not there any more.")
            return False
        self._path = montage
        self._labels = dict(labels or {})
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
        self.elapsed.setText(counter_label(0.0, self.timeline.duration_s))
        self.clip_line.setText("")
        return True

    def clear(self) -> None:
        """Forget the montage, which is what a changed edit means."""
        self.stop()
        self._parts = []
        self._path = None
        self._labels = {}
        self.timeline.set_parts([])
        self.stack.setCurrentWidget(self.placeholder)
        self.clip_line.clear()
        self.elapsed.clear()
        self._set_enabled(False)

    def take_strip(self) -> QWidget:
        """Hand the strip and its key hints to a screen that wants them elsewhere.

        The player keeps driving it: it is the same widget, only reparented, so seeking
        and following the playhead work exactly as they did.
        """
        self.strip.setParent(None)
        return self.strip

    def _set_enabled(self, on: bool) -> None:
        for widget in (self.play_button, self.restart_button, self.timeline):
            widget.setEnabled(on)

    # --- the player --------------------------------------------------------

    def _build_player(self, video_output: Any | None) -> QMediaPlayer | None:
        """The player with its outputs attached, built on first use.

        Attached before any source is set, for the reason issue 38 recorded: a player
        with no video output decodes every frame, throws it away and reports nothing.
        """
        video_output = checked_video_output(video_output, "MontagePlayer video output")
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
        self.elapsed.setText(counter_label(seconds, self.timeline.duration_s))
        part = clip_at(self._parts, seconds)
        if part is not None and part.order != self._current_order:
            self._announce(part)

    def describe(self, part: Part) -> str:
        """What the transport says about one clip. The id is the last resort."""
        return self._labels.get(part.segment_id, part.segment_id)

    def _announce(self, part: Part) -> None:
        self._current_order = part.order
        self.clip_line.setText(f"Clip {part.order} of {len(self._parts)} · {self.describe(part)}")
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

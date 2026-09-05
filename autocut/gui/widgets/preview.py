"""Watching one clip, and moving its in and out points.

Playback is a convenience; the decision is the point. So the panel is built to be
useful without a working codec: the sprite strip and the bounds sliders answer "is
this the moment" on their own, and the video takes their place when the platform can
decode the file. HEVC 10-bit from a drone plays on macOS and often does not on Linux
(design note), and a panel that is empty in that case would make the screen useless
on the machine this is developed on.

A player needs somewhere to put its frames. Without ``setVideoOutput`` Qt decodes the
file, discards every frame and reports no error, which is what issue 38 was: the logs
showed the probe, the picture never changed, and nothing looked broken. So the video
output is attached before the source is set, an audio output goes with it because a
player with no audio output is silent whatever the file holds, and the seek waits for
``LoadedMedia`` because a position set before that is dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from autocut.core.manifest import Segment
from autocut.gui import theme
from autocut.gui.models import clock_label
from autocut.gui.state import ProjectState
from autocut.gui.widgets.scrubber import StripCache
from autocut.gui.widgets.video import checked_video_output

if TYPE_CHECKING:  # pragma: no cover - imported for the annotations only
    from PySide6.QtMultimedia import QMediaPlayer

#: Bounds are integers in a slider, seconds in the manifest. A millisecond step is
#: finer than the sampling grid, which is what the values are snapped to anyway.
MS = 1000

#: How far past the out point the player may run before it is paused. One frame at
#: 25 fps: ``positionChanged`` does not fire on every frame, and stopping early would
#: cut the last moment of the clip a reviewer is judging.
OUT_TOLERANCE_MS = 40


def snap(value: float, sample_fps: float) -> float:
    """The nearest instant the analysis sampled. The unit of a bound is a sampled frame."""
    if sample_fps <= 0:
        return value
    return round(value * sample_fps) / sample_fps


class PreviewPanel(QWidget):
    """The current clip: a picture, a scrub bar, and the two bounds.

    ``QMediaPlayer`` is created on demand and only when the platform reports it can
    play the file, so a machine without the codecs shows the strip and the bounds
    rather than a black rectangle and a silent failure.
    """

    bounds_committed = Signal(str, object)
    """Segment id and either a ``(start, end)`` tuple or ``None`` to clear."""

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._segment_id = ""
        self._strips = StripCache(self)

        metrics = theme.current().metrics
        self.title = QLabel("Nothing selected")
        self.title.setProperty("role", "title")
        # Where in the day and how long the source clip is, in the mono face, on the
        # right of the file name. The numbers a reviewer compares live in one column.
        self.meta = QLabel("")
        self.meta.setProperty("role", "muted")
        self.meta.setFont(theme.font(metrics.body_size, mono=True))
        self.meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.frame = QLabel()
        self.frame.setMinimumHeight(metrics.preview_height)
        self.frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame.setProperty("role", "placeholder")
        self.frame.setText("no preview")

        # The strip and the video take the same place rather than sitting one above
        # the other: they answer the same question, and two pictures of one clip is
        # one picture too many.
        self.picture_stack = QStackedWidget()
        self.picture_stack.addWidget(self.frame)
        self.video: QWidget | None = None

        self.scrub = QSlider(Qt.Orientation.Horizontal)
        self.scrub.setRange(0, MS)
        self.scrub.valueChanged.connect(self._scrubbed)

        self.start_slider = QSlider(Qt.Orientation.Horizontal)
        self.end_slider = QSlider(Qt.Orientation.Horizontal)
        for slider in (self.start_slider, self.end_slider):
            slider.setRange(0, MS)
            slider.sliderReleased.connect(self._commit_bounds)
        self.start_slider.valueChanged.connect(self._bounds_moved)
        self.end_slider.valueChanged.connect(self._bounds_moved)

        self.bounds_label = QLabel("")
        self.bounds_label.setFont(theme.font(metrics.body_size, mono=True))
        self.bounds_label.setProperty("role", "muted")
        self.bounds_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.bounds_heading = QLabel("In · Out")
        self.bounds_heading.setProperty("role", "label")

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setProperty("role", "muted")

        self.clear_button = QPushButton("Automatic window")
        self.clear_button.clicked.connect(self._clear_bounds)
        self.play_button = QPushButton("Play clip")
        self.play_button.setProperty("variant", "quiet")
        # Through a lambda, not straight to play: clicked carries the button's checked
        # state, and connecting it directly handed False to setVideoOutput.
        self.play_button.clicked.connect(lambda: self.play())
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        # Muted by default: every clip is exported silent and the soundtrack carries
        # the sound, so a preview that started making noise would be a surprise.
        self.sound_box = QCheckBox("Sound")
        self.sound_box.toggled.connect(self._sound_toggled)

        heading = QHBoxLayout()
        heading.setSpacing(metrics.space)
        heading.addWidget(self.title, 1)
        heading.addWidget(self.meta)

        bounds_heading = QHBoxLayout()
        bounds_heading.setSpacing(metrics.space)
        bounds_heading.addWidget(self.bounds_heading)
        bounds_heading.addWidget(self.bounds_label, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(metrics.space)
        buttons.addWidget(self.play_button, 1)
        buttons.addWidget(self.clear_button, 1)

        transport = QHBoxLayout()
        transport.setSpacing(metrics.space)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.sound_box)
        transport.addStretch(1)

        # The order the spec fixes: the file, the picture, the bounds as numbers and as
        # a bar, then the two actions. Everything a reviewer does to one clip, downwards.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(metrics.space + 2)
        layout.addLayout(heading)
        layout.addWidget(self.picture_stack, 1)
        layout.addWidget(self.scrub)
        layout.addLayout(bounds_heading)
        layout.addWidget(self.start_slider)
        layout.addWidget(self.end_slider)
        layout.addLayout(buttons)
        layout.addLayout(transport)
        layout.addWidget(self.note)

        self._player: QMediaPlayer | None = None
        self._audio: Any | None = None
        self._pending_seek_ms: int | None = None
        self._out_ms: int | None = None
        self.playing_segment_id = ""
        self.show_segment("")

    # --- what is on screen -------------------------------------------------

    @property
    def segment_id(self) -> str:
        return self._segment_id

    def show_segment(self, segment_id: str) -> None:
        """Point the panel at a segment, or clear it with an empty id.

        Moving to another clip stops the player: a preview of the clip before the one
        on screen is worse than no preview, and the reviewer has already moved on.
        """
        if segment_id != self.playing_segment_id and self.playing_segment_id:
            self.stop()
        self._segment_id = segment_id
        segment = self._state.segment(segment_id) if segment_id else None
        enabled = segment is not None
        for widget in (
            self.scrub,
            self.start_slider,
            self.end_slider,
            self.clear_button,
            self.play_button,
        ):
            widget.setEnabled(enabled)
        if segment is None:
            self.title.setText("Nothing selected")
            self.meta.clear()
            self.frame.setText("no preview")
            self.show_strip()
            self.bounds_label.clear()
            self.note.clear()
            return

        source = self._state.manifest.files.get(segment.file_id) if self._state.manifest else None
        name = Path(source.path).name if source is not None else segment.file_id
        self.title.setText(name)
        length = f"{segment.end_s - segment.start_s:.1f} s"
        clock = clock_label(source, segment.start_s)
        self.meta.setText(f"{clock} · {length}" if clock else length)
        self._span = _trimmed(segment)
        start, end = segment.effective_bounds
        for slider, value in ((self.start_slider, start), (self.end_slider, end)):
            slider.blockSignals(True)
            slider.setValue(self._to_slider(value))
            slider.blockSignals(False)
        self.scrub.blockSignals(True)
        self.scrub.setValue(self._to_slider(segment.effective_center))
        self.scrub.blockSignals(False)
        self._update_bounds_label()
        self._show_frame(self.scrub.value() / MS)
        self.note.setText(
            "In and out snap to the sampling grid, which is the finest position the "
            "analysis measured."
        )

    # --- the picture -------------------------------------------------------

    def _show_frame(self, fraction: float) -> None:
        segment = self._state.segment(self._segment_id)
        manifest = self._state.manifest
        if segment is None or manifest is None:
            return
        strip = self._strips.strip(manifest, segment, self._state.config)
        if strip is None:
            self.frame.setText("no strip for this clip; run the analysis with sprites on")
            return
        pixmap = strip.frame_at(fraction)
        if pixmap.isNull():
            self.frame.setText("no preview")
            return
        self.frame.setPixmap(
            pixmap.scaled(
                self.frame.width(),
                self.frame.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _scrubbed(self, value: int) -> None:
        """Dragging the scrub bar is asking for the strip, not for the video."""
        if self.playing_segment_id:
            self.stop()
        self._show_frame(value / MS)

    def _build_player(self, video_output: Any | None) -> QMediaPlayer | None:
        """The player, its audio output and somewhere to put the frames.

        Built on the first Play rather than with the panel: ``QtMultimedia`` pulls in
        the platform's media stack, which is a slow import and, on a machine without
        the codecs, a noisy one. Both outputs are attached before any source is set,
        because a player with no video output decodes every frame and throws it away
        without reporting anything wrong, which is what issue 38 was.
        """
        if self._player is not None:
            if video_output is not None:
                self._player.setVideoOutput(video_output)
            return self._player
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except ImportError:
            self.note.setText(
                "Playback needs the Qt multimedia module, which this build does not "
                "have. The strip above is the clip, frame by frame."
            )
            return None

        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        audio.setMuted(not self.sound_box.isChecked())
        player.setAudioOutput(audio)
        self._audio = audio

        if video_output is None:
            video = QVideoWidget()
            video.setMinimumHeight(180)
            self.video = video
            self.picture_stack.addWidget(video)
            video_output = video
        player.setVideoOutput(video_output)

        player.mediaStatusChanged.connect(self._media_status_changed)
        player.positionChanged.connect(self._position_changed)
        player.playbackStateChanged.connect(self._playback_state_changed)
        player.errorOccurred.connect(self._playback_failed)
        self._player = player
        return player

    def play(self, video_output: Any | None = None) -> bool:
        """Play the current clip from its in point. False when there is nothing to play.

        ``video_output`` is for a test that wants the frames in a ``QVideoSink`` it can
        count; the window passes nothing and gets the panel's own video widget.
        """
        segment = self._state.segment(self._segment_id)
        manifest = self._state.manifest
        if segment is None or manifest is None:
            return False
        source = manifest.files.get(segment.file_id)
        if source is None:
            return False
        path = Path(source.proxy_path or source.path)
        if not path.exists():
            self.note.setText(f"{path} is not where the manifest says it is.")
            return False
        player = self._build_player(checked_video_output(video_output, "PreviewPanel.play"))
        if player is None:
            return False

        start, end = segment.effective_bounds
        # Kept rather than applied: a position set before the media reaches
        # LoadedMedia is dropped, and the clip then plays from the top of the file.
        self._pending_seek_ms = int(start * 1000)
        self._out_ms = int(end * 1000)
        self.playing_segment_id = self._segment_id
        self.note.setText(f"Loading {path.name}…")
        player.setSource(QUrl.fromLocalFile(str(path)))
        if player.mediaStatus() in self._ready_states():
            # Already loaded, which happens when the same file is played twice: the
            # status will not change again, so there is no signal coming.
            self._start_playing()
        return True

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
        self.playing_segment_id = ""
        self.show_strip()

    def show_strip(self) -> None:
        """Put the sprite strip back in front of the video."""
        self.picture_stack.setCurrentWidget(self.frame)

    def show_video(self) -> None:
        if self.video is not None:
            self.picture_stack.setCurrentWidget(self.video)

    @staticmethod
    def _ready_states() -> tuple[Any, ...]:
        from PySide6.QtMultimedia import QMediaPlayer

        return (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
        )

    def _media_status_changed(self, status: Any) -> None:
        """Seek and start once the media is loaded, and only then judge the video."""
        from PySide6.QtMultimedia import QMediaPlayer

        if status in self._ready_states():
            self._start_playing()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            # The file ran out before the out point, which happens when a segment's
            # bounds came from a manifest written against a longer file. Saying so
            # beats leaving "playing from the in point" under a still picture.
            self.note.setText("The file ended before the out point.")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.show_strip()
            self.note.setText(
                "The platform could not open this file. The strip above is the clip, "
                "frame by frame."
            )

    def _start_playing(self) -> None:
        player = self._player
        if player is None:
            return
        if self._pending_seek_ms is not None:
            player.setPosition(self._pending_seek_ms)
            self._pending_seek_ms = None
        if player.hasVideo():
            self.show_video()
            self.note.setText("Playing from the in point. It pauses at the out point.")
        else:
            # Loaded, no video track the platform can give us: the strip is the clip.
            self.show_strip()
            self.note.setText(
                "The platform has no decoder for this file, so the strip above is the "
                "clip, frame by frame."
            )
        player.play()

    def _position_changed(self, position_ms: int) -> None:
        """Pause at the out point, so a preview shows the clip and not the rest of the file."""
        player = self._player
        if player is None or self._out_ms is None:
            return
        if position_ms >= self._out_ms - OUT_TOLERANCE_MS:
            player.pause()
            self.note.setText("Paused at the out point.")

    def _playback_state_changed(self, state: Any) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.stop_button.setEnabled(playing)
        self.play_button.setText("Play" if not playing else "Playing…")

    def _playback_failed(self, error: Any, message: str = "") -> None:
        del error
        self.show_strip()
        self.note.setText(
            f"Playback failed: {message or 'the platform would not open this file'}. "
            "The strip above is the clip, frame by frame."
        )

    def _sound_toggled(self, on: bool) -> None:
        if self._audio is not None:
            self._audio.setMuted(not on)

    # --- the bounds --------------------------------------------------------

    def _to_slider(self, seconds: float) -> int:
        start, end = self._span
        span = max(end - start, 1e-6)
        return int(round((seconds - start) / span * MS))

    def _from_slider(self, value: int) -> float:
        start, end = self._span
        return start + (end - start) * value / MS

    def bounds(self) -> tuple[float, float]:
        """The two bounds as seconds, snapped, in order."""
        sample_fps = self._state.config.analysis.sample_fps
        start = snap(self._from_slider(self.start_slider.value()), sample_fps)
        end = snap(self._from_slider(self.end_slider.value()), sample_fps)
        return (start, end) if end > start else (end, start)

    def _bounds_moved(self) -> None:
        self._update_bounds_label()
        self._show_frame(self.start_slider.value() / MS)

    def _update_bounds_label(self) -> None:
        """`5.50 s → 9.80 s · 4.30 s`, in the mono face, beside its label."""
        start, end = self.bounds()
        self.bounds_label.setText(f"{start:.2f} s → {end:.2f} s · {end - start:.2f} s")

    def _commit_bounds(self) -> None:
        """Save the drag. A span shorter than one sampled frame is a slip, not a decision."""
        if not self._segment_id:
            return
        start, end = self.bounds()
        sample_fps = self._state.config.analysis.sample_fps
        step = 1.0 / sample_fps if sample_fps > 0 else 0.0
        if end - start <= step:
            self.note.setText("That is shorter than one sampled frame, so it was not saved.")
            return
        self.bounds_committed.emit(self._segment_id, (start, end))

    def _clear_bounds(self) -> None:
        if self._segment_id:
            self.bounds_committed.emit(self._segment_id, None)


def _trimmed(segment: Segment) -> tuple[float, float]:
    """The span the sliders move in: the trim, not the hand set bounds.

    A bound has to be draggable back out again, so the range is the shot as the trim
    left it, even when the reviewer has already narrowed it.
    """
    start = segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
    end = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
    return start, max(end, start + 1e-6)

"""Playing a clip in the preview panel: frames arrive, and it stops at the out point.

Issue 38 was a player with nowhere to put its frames: Qt decoded the file, discarded
every frame and reported no error, so the picture never changed and nothing looked
broken. The only test that catches that is one that counts frames, which is what a
``QVideoSink`` is for.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtMultimedia")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink  # noqa: E402

from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from autocut.gui.widgets.preview import PreviewPanel  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.ffmpeg]

CLIP = "sharp_pan.mp4"


def project_over(clip: Path, tmp_path: Path, span: tuple[float, float] = (0.0, 6.0)) -> Manifest:
    """A one clip project pointing at a real file, so the player has something to open."""
    now = datetime.now(UTC)
    out = tmp_path / "edit"
    out.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(created_at=now, updated_at=now, sources=[clip.parent], output_dir=out)
    manifest.files["f0"] = SourceFile(
        id="f0",
        path=clip,
        source_class="actioncam",
        duration_s=6.0,
        width=1280,
        height=720,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
    )
    manifest.segments["f0:0"] = Segment(
        id="f0:0",
        file_id="f0",
        start_s=span[0],
        end_s=span[1],
        trimmed_start_s=span[0],
        trimmed_end_s=span[1],
        best_center_s=(span[0] + span[1]) / 2.0,
        outcome="selected",
        order=1,
        score=0.5,
        metrics=Metrics(
            sharpness=100.0,
            exposure_clipped=0.0,
            motion=0.3,
            stability=0.9,
            colorfulness=0.2,
        ),
    )
    return manifest


@pytest.fixture
def panel(qtbot: Any, tmp_path: Path, synthetic_dir: Path) -> PreviewPanel:
    state = ProjectState()
    state.config.cache.dir = tmp_path / "cache"
    manifest = project_over(synthetic_dir / CLIP, tmp_path)
    manifest.save(tmp_path / "edit" / "manifest.json")
    state.open_project(tmp_path / "edit")
    widget = PreviewPanel(state)
    qtbot.addWidget(widget)
    widget.resize(640, 480)
    widget.show_segment("f0:0")
    return widget


def wait_for(qtbot: Any, predicate: Any, timeout: int = 20_000) -> bool:
    """Spin the event loop until ``predicate`` holds. Playback is asynchronous."""
    try:
        qtbot.waitUntil(predicate, timeout=timeout)
    except AssertionError:
        return False
    return True


def test_frames_reach_the_video_output(panel: PreviewPanel, qtbot: Any) -> None:
    """The regression test for issue 38: a player with an output delivers frames.

    Counted in a sink rather than looked for on a widget, because a widget cannot be
    asked how many frames it painted and this is exactly the claim that was false.
    """
    sink = QVideoSink()
    frames: list[int] = []
    sink.videoFrameChanged.connect(lambda frame: frames.append(1) if frame.isValid() else None)

    assert panel.play(video_output=sink)

    assert wait_for(qtbot, lambda: len(frames) > 5), f"only {len(frames)} frames arrived"
    assert panel._player is not None
    assert panel._player.hasVideo()


def test_the_seek_lands_after_the_media_is_loaded(panel: PreviewPanel, qtbot: Any) -> None:
    """A position set before ``LoadedMedia`` is dropped and the clip plays from the top."""
    state = panel._state
    segment = state.segment("f0:0")
    assert segment is not None
    segment.user_start_s = 2.0
    segment.user_end_s = 5.0
    panel.show_segment("f0:0")
    sink = QVideoSink()

    assert panel.play(video_output=sink)
    player = panel._player
    assert player is not None
    assert wait_for(qtbot, lambda: player.mediaStatus() in panel._ready_states())
    assert wait_for(qtbot, lambda: player.position() > 0)

    # Started at the in point, not at the top of the file.
    assert player.position() >= 1800


def test_playback_pauses_at_the_out_point(panel: PreviewPanel, qtbot: Any) -> None:
    """A preview shows the clip, not the rest of the file."""
    state = panel._state
    segment = state.segment("f0:0")
    assert segment is not None
    segment.user_start_s = 0.5
    segment.user_end_s = 1.5
    panel.show_segment("f0:0")
    sink = QVideoSink()

    assert panel.play(video_output=sink)
    player = panel._player
    assert player is not None

    assert wait_for(
        qtbot, lambda: player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    ), f"still {player.playbackState()} at {player.position()} ms"
    # Paused at the out point, within the tolerance a coarse positionChanged needs.
    assert 1200 <= player.position() <= 1900
    assert "out point" in panel.note.text()


def test_a_file_that_ends_before_the_out_point_says_so(panel: PreviewPanel, qtbot: Any) -> None:
    """Found on the real footage: a 1.9 s clip against bounds that ask for 5 s.

    Leaving "playing from the in point" under a still picture is the same class of
    silence as issue 38 itself.
    """
    state = panel._state
    segment = state.segment("f0:0")
    assert segment is not None
    # Past the end of the six second fixture, which is what a stale manifest looks like.
    segment.user_start_s = 5.5
    segment.user_end_s = 12.0
    panel.show_segment("f0:0")
    sink = QVideoSink()

    assert panel.play(video_output=sink)

    assert wait_for(qtbot, lambda: "ended before the out point" in panel.note.text())


def test_the_player_has_an_audio_output_and_starts_muted(panel: PreviewPanel) -> None:
    """A player with no audio output is silent whatever the file holds, and every clip
    is exported silent, so the sound is off until it is asked for."""
    sink = QVideoSink()

    assert panel.play(video_output=sink)

    player = panel._player
    assert player is not None
    assert player.audioOutput() is not None
    assert player.audioOutput().isMuted()

    panel.sound_box.setChecked(True)
    assert not player.audioOutput().isMuted()


def test_the_video_widget_takes_the_place_of_the_strip(panel: PreviewPanel, qtbot: Any) -> None:
    """The window's own path: no sink, so the panel builds and shows its video widget."""
    assert panel.picture_stack.currentWidget() is panel.frame

    assert panel.play()

    assert panel.video is not None
    # Waited on the note, not on the page: the page is shown before the source is set
    # now, so the video being current no longer means playback has started.
    assert wait_for(qtbot, lambda: "Playing from the in point" in panel.note.text())
    assert panel.picture_stack.currentWidget() is panel.video


def test_stopping_puts_the_strip_back(panel: PreviewPanel, qtbot: Any) -> None:
    assert panel.play()
    assert wait_for(qtbot, lambda: panel.playing_segment_id == "f0:0")

    panel.stop()

    assert panel.picture_stack.currentWidget() is panel.frame
    assert panel.playing_segment_id == ""
    assert not panel.stop_button.isEnabled()


def test_moving_to_another_clip_stops_the_player(
    panel: PreviewPanel, qtbot: Any, synthetic_dir: Path
) -> None:
    """A preview of the clip before the one on screen is worse than no preview."""
    state = panel._state
    manifest = state.manifest
    assert manifest is not None
    manifest.files["f1"] = manifest.files["f0"].model_copy(update={"id": "f1"})
    manifest.segments["f1:0"] = manifest.segments["f0:0"].model_copy(
        update={"id": "f1:0", "file_id": "f1"}
    )
    assert panel.play()
    assert wait_for(qtbot, lambda: panel.playing_segment_id == "f0:0")

    panel.show_segment("f1:0")

    assert panel.playing_segment_id == ""
    assert panel.picture_stack.currentWidget() is panel.frame


def test_scrubbing_stops_the_player_and_shows_the_strip(panel: PreviewPanel, qtbot: Any) -> None:
    assert panel.play()
    assert wait_for(qtbot, lambda: panel.playing_segment_id == "f0:0")

    panel.scrub.setValue(600)

    assert panel.playing_segment_id == ""
    assert panel.picture_stack.currentWidget() is panel.frame


def test_a_missing_file_says_so_rather_than_playing_nothing(
    panel: PreviewPanel, tmp_path: Path
) -> None:
    manifest = panel._state.manifest
    assert manifest is not None
    manifest.files["f0"].path = tmp_path / "gone.mp4"

    assert panel.play() is False

    assert "is not where the manifest says it is" in panel.note.text()


def test_playing_twice_starts_from_the_in_point_again(panel: PreviewPanel, qtbot: Any) -> None:
    """The same file twice sends no status change, so the second play needs no signal."""
    sink = QVideoSink()
    assert panel.play(video_output=sink)
    player = panel._player
    assert player is not None
    assert wait_for(qtbot, lambda: player.position() > 300)
    panel.stop()

    assert panel.play(video_output=sink)

    assert wait_for(
        qtbot, lambda: player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    )


# --- the Play buttons, pressed the way a user presses them -------------------


def test_pressing_play_builds_a_player_with_a_video_widget(panel: PreviewPanel, qtbot: Any) -> None:
    """The macOS regression: `clicked` carries a bool, and it reached setVideoOutput.

    Pressed through the widget rather than by calling `play()`, because calling the
    method directly is exactly what the broken connection did not do. On the Mac this
    raised inside Qt with a message about argument types and nothing about the button.
    """
    from PySide6.QtMultimediaWidgets import QVideoWidget

    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)

    assert panel._player is not None
    assert isinstance(panel.video, QVideoWidget)
    assert panel._player.videoOutput() is panel.video
    panel.stop()


def test_a_bool_video_output_is_refused_by_name(panel: PreviewPanel) -> None:
    """What a direct `clicked.connect(self.play)` would hand in, caught where it means
    something rather than deep inside Qt."""
    with pytest.raises(TypeError, match="PreviewPanel.play"):
        panel.play(False)
    with pytest.raises(TypeError, match="zero argument slot"):
        panel.play(True)


def test_a_real_video_output_is_still_accepted(panel: PreviewPanel) -> None:
    """The guard must not get in the way of the sink the other tests count frames in."""
    sink = QVideoSink()
    assert panel.play(sink)
    assert panel._player is not None
    assert panel._player.videoOutput() is sink
    panel.stop()


# --- Stop after the pause at the out point ----------------------------------


def test_stop_is_enabled_once_playback_pauses(panel: PreviewPanel, qtbot: Any) -> None:
    """The macOS defect: Stop followed PlayingState, so the out point pause disabled it.

    Playback pauses at the out point by design, and the user was then left with a
    paused player and a dead Stop button. Driven through the signal rather than by
    waiting for a real pause, so the test states the rule rather than the timing.
    """
    assert panel.play()
    panel._playback_state_changed(QMediaPlayer.PlaybackState.PausedState)

    assert panel.stop_button.isEnabled(), "Stop is dead while the player is paused"
    panel.stop()


def test_stop_is_enabled_while_playing_and_dead_before_anything_plays(
    panel: PreviewPanel, qtbot: Any
) -> None:
    del qtbot
    assert not panel.stop_button.isEnabled()

    assert panel.play()

    assert panel.stop_button.isEnabled()
    panel.stop()


def test_pressing_stop_after_the_out_point_returns_to_the_strip(
    panel: PreviewPanel, qtbot: Any
) -> None:
    """The scenario from the spec, pressed through the widget."""
    assert panel.play()
    assert wait_for(qtbot, lambda: panel.picture_stack.currentWidget() is not panel.frame)
    panel._playback_state_changed(QMediaPlayer.PlaybackState.PausedState)
    panel.note.setText("Loading something…")

    qtbot.mouseClick(panel.stop_button, Qt.MouseButton.LeftButton)

    assert panel.picture_stack.currentWidget() is panel.frame
    assert panel.note.text() == ""
    assert panel.play_button.isEnabled()
    assert panel.playing_segment_id == ""


def test_stopping_puts_the_scrub_back_at_the_in_point(panel: PreviewPanel, qtbot: Any) -> None:
    """A stopped clip is ready to play again from where it starts, not from the end."""
    segment = panel._state.segment("f0:0")
    assert segment is not None
    start, _end = segment.effective_bounds
    assert panel.play()
    assert wait_for(qtbot, lambda: panel.scrub.value() > panel._to_slider(start))

    panel.stop()

    assert panel.scrub.value() == panel._to_slider(start)


# --- the native video layer on macOS ----------------------------------------


def test_showing_the_strip_hides_the_video_widget(panel: PreviewPanel, qtbot: Any) -> None:
    """On macOS `QVideoWidget` is a native NSView layered over the Qt scene.

    `setCurrentWidget` reorders Qt's own stack, which is enough on Linux and does
    nothing to a native layer: the user pressed Stop, the button worked, and the black
    rectangle stayed where it was. So the widget is hidden explicitly as well.

    This assertion cannot fail on Linux, because a `QStackedWidget` already sets the
    hidden flag on the page it is not showing and nothing here can see the native
    layer underneath. It is here for the platform where the two differ; the checks
    that bind everywhere are the detached output below.
    """
    assert panel.play()
    assert wait_for(qtbot, lambda: panel.video is not None)
    panel.show_video()
    assert panel.video is not None

    panel.show_strip()

    assert panel.picture_stack.currentWidget() is panel.frame
    assert panel.video.isHidden(), "the video widget is still on top of the strip"


def test_showing_the_video_puts_it_back(panel: PreviewPanel, qtbot: Any) -> None:
    assert panel.play()
    assert wait_for(qtbot, lambda: panel.video is not None)
    panel.show_strip()

    panel.show_video()

    assert panel.video is not None
    assert not panel.video.isHidden()
    assert panel.picture_stack.currentWidget() is panel.video


def test_stopping_detaches_the_video_output(panel: PreviewPanel, qtbot: Any) -> None:
    """A player still rendering into a native layer is a layer that stays black."""
    assert panel.play()
    assert wait_for(qtbot, lambda: panel._player is not None)

    panel.stop()

    assert panel._player is not None
    assert panel._player.videoOutput() is None
    assert panel.video is None or panel.video.isHidden()


def test_playing_again_after_a_stop_reattaches_the_video(panel: PreviewPanel, qtbot: Any) -> None:
    """Detaching on stop must not make the second Play a black rectangle."""
    assert panel.play()
    assert wait_for(qtbot, lambda: panel._player is not None)
    panel.stop()

    assert panel.play()

    assert panel._player is not None
    assert panel._player.videoOutput() is not None
    assert panel.video is not None


def test_a_playback_error_shows_the_strip_and_leaves_the_buttons_usable(
    panel: PreviewPanel, qtbot: Any
) -> None:
    """An error must not leave a black page with a Stop that does nothing."""
    del qtbot
    assert panel.play()

    panel._playback_failed(QMediaPlayer.Error.ResourceError, "no decoder for this file")

    assert panel.picture_stack.currentWidget() is panel.frame
    assert panel.video is None or panel.video.isHidden()
    assert "no decoder for this file" in panel.note.text()
    assert panel.play_button.isEnabled()
    assert not panel.stop_button.isEnabled()


def test_a_playback_error_is_logged_for_the_terminal(
    panel: PreviewPanel, caplog: pytest.LogCaptureFixture
) -> None:
    """A Mac reports what its terminal said, so the error has to reach the terminal."""
    assert panel.play()

    with caplog.at_level(logging.WARNING):
        panel._playback_failed(QMediaPlayer.Error.FormatError, "unsupported format")

    assert any("unsupported format" in record.message for record in caplog.records)


def test_invalid_media_shows_the_strip_and_frees_the_buttons(
    panel: PreviewPanel, qtbot: Any
) -> None:
    del qtbot
    assert panel.play()

    panel._media_status_changed(QMediaPlayer.MediaStatus.InvalidMedia)

    assert panel.picture_stack.currentWidget() is panel.frame
    assert panel.video is None or panel.video.isHidden()
    assert not panel.stop_button.isEnabled()
    assert panel.play_button.isEnabled()


def test_the_video_page_is_realised_before_the_source_is_set(
    panel: PreviewPanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first Play was black and the second was fine, which is an ordering bug.

    On macOS the video widget is a native NSView created when it is first shown, so a
    layer that comes into existence after the first frame was decoded never paints it.
    Linux cannot see the difference, so what is asserted is the order itself, which is
    the thing that was wrong.
    """
    order: list[str] = []
    real_show_video = PreviewPanel.show_video
    real_set_source = QMediaPlayer.setSource

    def traced_show(self: PreviewPanel) -> None:
        order.append("show video")
        real_show_video(self)

    def traced_source(self: QMediaPlayer, url: Any) -> None:
        order.append("set source")
        real_set_source(self, url)

    monkeypatch.setattr(PreviewPanel, "show_video", traced_show)
    monkeypatch.setattr(QMediaPlayer, "setSource", traced_source)

    assert panel.play()

    assert order[:2] == ["show video", "set source"], order


def test_stop_pauses_before_it_stops(panel: PreviewPanel, qtbot: Any) -> None:
    """`stop()` alone left the last frame on the native layer on macOS."""
    del qtbot
    assert panel.play()
    assert panel._player is not None
    calls: list[str] = []
    panel._player.pause = lambda: calls.append("pause")  # type: ignore[method-assign]
    panel._player.stop = lambda: calls.append("stop")  # type: ignore[method-assign]

    panel.stop()

    assert calls == ["pause", "stop"]


def test_the_playback_sequence_is_logged_for_a_mac_terminal(
    panel: PreviewPanel, caplog: pytest.LogCaptureFixture
) -> None:
    """A report from another machine is whatever its terminal said."""
    from PySide6.QtMultimedia import QMediaPlayer

    with caplog.at_level(logging.DEBUG, logger="autocut.gui.widgets.preview"):
        assert panel.play()
        panel._playback_state_changed(QMediaPlayer.PlaybackState.PlayingState)
        panel._media_status_changed(QMediaPlayer.MediaStatus.BufferedMedia)

    messages = [record.getMessage() for record in caplog.records]
    assert any("playing" in message for message in messages)
    assert any("playback state" in message for message in messages)
    assert any("media status" in message for message in messages)


def test_stop_says_it_ran_before_it_does_anything(
    panel: PreviewPanel, caplog: pytest.LogCaptureFixture
) -> None:
    """The Mac reported that Stop printed nothing at all.

    With no line at the top of the slot, an empty log cannot tell a slot that never
    ran from a native layer that would not go away, and those need different fixes.
    """
    assert panel.play()

    with caplog.at_level(logging.INFO, logger="autocut.gui.widgets.preview"):
        panel.stop()

    assert any("stop pressed" in record.getMessage() for record in caplog.records)

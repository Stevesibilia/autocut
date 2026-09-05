"""Playing a clip in the preview panel: frames arrive, and it stops at the out point.

Issue 38 was a player with nowhere to put its frames: Qt decoded the file, discarded
every frame and reported no error, so the picture never changed and nothing looked
broken. The only test that catches that is one that counts frames, which is what a
``QVideoSink`` is for.
"""

from __future__ import annotations

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
    assert wait_for(qtbot, lambda: panel.picture_stack.currentWidget() is panel.video)
    assert "Playing from the in point" in panel.note.text()


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

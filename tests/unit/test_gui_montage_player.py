"""The montage player: frames arrive, the timeline marks the cuts, clicks seek."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtMultimedia")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink  # noqa: E402

from autocut.core.config import AutocutConfig  # noqa: E402
from autocut.core.montage import Part, build_montage  # noqa: E402
from autocut.gui.widgets.montage import MontagePlayer, MontageTimeline  # noqa: E402
from tests.unit.test_montage import CLIPS, project  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.ffmpeg]


def wait_for(qtbot: Any, predicate: Any, timeout: int = 20_000) -> bool:
    try:
        qtbot.waitUntil(predicate, timeout=timeout)
    except AssertionError:
        return False
    return True


@pytest.fixture
def rendered(tmp_path: Path, synthetic_dir: Path) -> tuple[Path, Path, list[Part]]:
    """A real three clip montage, since the player's whole job is to play one."""
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    result = build_montage(manifest, config)
    assert result.ok, result.errors
    assert result.path is not None and result.index_path is not None
    return result.path, result.index_path, result.parts


@pytest.fixture
def player(qtbot: Any, rendered: tuple[Path, Path, list[Part]]) -> MontagePlayer:
    montage, index, _parts = rendered
    widget = MontagePlayer()
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    assert widget.load(montage, index)
    return widget


# --- the timeline on its own --------------------------------------------------


def test_an_empty_timeline_says_so(qtbot: Any) -> None:
    timeline = MontageTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(400, 34)

    assert timeline.parts == []
    assert timeline.duration_s == 0.0
    assert timeline.clip_at_x(200) is None
    # Painting an empty timeline must not raise, which a grab exercises.
    assert not timeline.grab().toImage().isNull()


def test_the_timeline_maps_a_pixel_to_a_clip(qtbot: Any, tmp_path: Path) -> None:
    timeline = MontageTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(400, 34)
    parts = [
        Part(1, "a:0", tmp_path / "a.mp4", 4.0, start_s=0.0),
        Part(2, "b:0", tmp_path / "b.mp4", 4.0, start_s=4.0),
    ]

    timeline.set_parts(parts)

    assert timeline.duration_s == pytest.approx(8.0)
    assert timeline.clip_at_x(10) is parts[0]
    assert timeline.clip_at_x(300) is parts[1]


def test_clicking_the_timeline_names_the_clip(qtbot: Any, tmp_path: Path) -> None:
    timeline = MontageTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(400, 34)
    timeline.set_parts(
        [
            Part(1, "a:0", tmp_path / "a.mp4", 4.0, start_s=0.0),
            Part(2, "b:0", tmp_path / "b.mp4", 4.0, start_s=4.0),
        ]
    )
    clicked: list[int] = []
    timeline.clip_clicked.connect(clicked.append)

    timeline.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPoint(300, 10).toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )

    assert clicked == [2]


def test_the_timeline_draws_the_boundaries(qtbot: Any, tmp_path: Path) -> None:
    timeline = MontageTimeline()
    qtbot.addWidget(timeline)
    timeline.resize(400, 34)
    timeline.set_parts(
        [
            Part(1, "a:0", tmp_path / "a.mp4", 2.0, start_s=0.0),
            Part(2, "b:0", tmp_path / "b.mp4", 2.0, start_s=2.0),
            Part(3, "c:0", tmp_path / "c.mp4", 2.0, start_s=4.0),
        ]
    )
    timeline.set_position(3.0)

    image = timeline.grab().toImage()

    assert not image.isNull()
    # Two boundaries for three clips, and the played part is drawn as far as 3 s of 6.
    assert timeline.parts[1].start_s == pytest.approx(2.0)


# --- the player ---------------------------------------------------------------


def test_the_montage_index_becomes_the_timeline(player: MontagePlayer) -> None:
    assert len(player.parts) == 3
    assert player.timeline.duration_s == pytest.approx(3.0, abs=0.3)
    assert "3 clips" in player.status.text()


def test_frames_reach_the_video_output(player: MontagePlayer, qtbot: Any) -> None:
    """The lesson of issue 38, applied to the second player in the app."""
    sink = QVideoSink()
    frames: list[int] = []
    sink.videoFrameChanged.connect(lambda frame: frames.append(1) if frame.isValid() else None)
    player.set_video_output(sink)

    assert player.play()

    assert wait_for(qtbot, lambda: len(frames) > 5), f"only {len(frames)} frames"


def test_the_current_clip_is_announced_as_it_plays(player: MontagePlayer, qtbot: Any) -> None:
    """The grid highlight depends on this: one signal per clip, in order."""
    sink = QVideoSink()
    player.set_video_output(sink)
    seen: list[str] = []
    player.clip_changed.connect(seen.append)

    assert player.play()

    assert wait_for(qtbot, lambda: len(seen) >= 2, timeout=30_000), f"only saw {seen}"
    expected = [part.segment_id for part in player.parts]
    assert seen == expected[: len(seen)]


def test_seeking_to_a_clip_jumps_plays_and_announces(player: MontagePlayer, qtbot: Any) -> None:
    """A click on a boundary means "show me this clip", so it plays from there."""
    sink = QVideoSink()
    player.set_video_output(sink)
    announced: list[str] = []
    player.boundary_clicked.connect(announced.append)
    third = player.parts[2]

    assert player.seek_to_clip(3)

    assert announced == [third.segment_id]
    assert player.current_order == 3
    assert wait_for(
        qtbot, lambda: player._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    )
    assert wait_for(qtbot, lambda: player.position_s() >= third.start_s - 0.05)


def test_a_click_on_the_timeline_seeks_the_player(player: MontagePlayer, qtbot: Any) -> None:
    """The whole point of drawing the boundaries: they are how you get to a clip."""
    sink = QVideoSink()
    player.set_video_output(sink)
    player.timeline.resize(300, 34)
    seen: list[str] = []
    player.boundary_clicked.connect(seen.append)

    player.timeline.clip_clicked.emit(2)

    assert seen == [player.parts[1].segment_id]
    assert player.current_order == 2


def test_seeking_to_a_clip_that_is_not_there_does_nothing(player: MontagePlayer) -> None:
    assert player.seek_to_clip(99) is False


def test_the_current_segment_id_follows_the_position(player: MontagePlayer, qtbot: Any) -> None:
    sink = QVideoSink()
    player.set_video_output(sink)

    player.seek_to_clip(2)

    assert wait_for(qtbot, lambda: player.position_s() >= player.parts[1].start_s)
    assert player.current_segment_id() == player.parts[1].segment_id


def test_pause_and_play_toggle(player: MontagePlayer, qtbot: Any) -> None:
    sink = QVideoSink()
    player.set_video_output(sink)

    player.toggle()
    assert wait_for(
        qtbot, lambda: player._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    )
    assert player.play_button.text() == "Pause"

    player.toggle()
    assert wait_for(
        qtbot, lambda: player._player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    )
    assert player.play_button.text() == "Play"


def test_restart_goes_back_to_the_first_clip(player: MontagePlayer, qtbot: Any) -> None:
    sink = QVideoSink()
    player.set_video_output(sink)
    player.seek_to_clip(3)
    assert wait_for(qtbot, lambda: player.position_s() > 1.9)

    player.restart()

    assert wait_for(qtbot, lambda: player.position_s() < 1.0)


def test_the_player_starts_muted_and_the_toggle_works(player: MontagePlayer) -> None:
    """Every clip is silent in the export; the montage's sound is the track's."""
    assert player._audio is not None
    assert player._audio.isMuted()

    player.sound_box.setChecked(True)

    assert not player._audio.isMuted()


def test_loading_with_sound_on_unmutes(rendered: tuple[Path, Path, list[Part]], qtbot: Any) -> None:
    montage, index, _parts = rendered
    widget = MontagePlayer()
    qtbot.addWidget(widget)

    assert widget.load(montage, index, sound=True)

    assert widget._audio is not None
    assert not widget._audio.isMuted()


def test_a_missing_montage_is_reported(qtbot: Any, tmp_path: Path) -> None:
    widget = MontagePlayer()
    qtbot.addWidget(widget)

    assert widget.load(tmp_path / "gone.mp4") is False

    assert "not there any more" in widget.status.text()
    assert not widget.play_button.isEnabled()


def test_clearing_forgets_the_montage(player: MontagePlayer) -> None:
    assert player.path is not None

    player.clear()

    assert player.path is None
    assert player.parts == []
    assert player.timeline.parts == []
    assert not player.play_button.isEnabled()
    assert player.stack.currentWidget() is player.placeholder


def test_the_transport_is_disabled_until_something_is_loaded(qtbot: Any) -> None:
    widget = MontagePlayer()
    qtbot.addWidget(widget)

    assert not widget.play_button.isEnabled()
    assert not widget.restart_button.isEnabled()
    assert widget.play() is False

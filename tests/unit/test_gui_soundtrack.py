"""The Soundtrack screen: the prompt blocks, the mood controls, the track and the beats."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from autocut.core.manifest import Manifest  # noqa: E402
from autocut.gui.screens.soundtrack import SoundtrackScreen  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from autocut.gui.widgets.prompt_editor import PromptEditor  # noqa: E402
from autocut.gui.widgets.waveform import (  # noqa: E402
    WaveformView,
    envelope_path,
    load_or_build_envelope,
)
from tests.unit.test_gui_review import reviewable  # noqa: E402

pytestmark = pytest.mark.gui

CLICK = "click_120bpm.wav"


@pytest.fixture
def screen(qtbot: Any, tmp_path: Path) -> SoundtrackScreen:
    """A selected project with a prompt already generated."""
    state = reviewable(tmp_path, tmp_path / "edit")
    widget = SoundtrackScreen(state)
    qtbot.addWidget(widget)
    widget.resize(1400, 880)
    assert widget.generate()
    return widget


# --- the prompt blocks --------------------------------------------------------


def test_the_screen_shows_the_matched_row_and_the_bpm(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None

    assert manifest.soundtrack.matched_row is not None
    assert manifest.soundtrack.matched_row in screen.matched_label.text()
    assert screen.bpm_field.value() == int(manifest.soundtrack.proposed_bpm or 0)
    assert screen.variant_box.count() == len(manifest.soundtrack.variants)


def test_the_blocks_hold_the_chosen_variant(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    chosen = manifest.soundtrack.variants[0]

    assert screen.editor.title.text() == chosen.title
    assert screen.editor.description.toPlainText() == chosen.description
    assert screen.editor.structure_lines() == chosen.structure


def test_copying_the_description_puts_exactly_that_on_the_clipboard(
    screen: SoundtrackScreen,
) -> None:
    """The scenario from the spec."""
    text = screen.editor.description.toPlainText()

    assert screen.editor.copy("Description")

    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == text


def test_copying_the_structure_gives_the_lines(screen: SoundtrackScreen) -> None:
    assert screen.editor.copy("Structure")

    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "\n".join(screen.editor.structure_lines())
    assert clipboard.text().endswith("[end]")


def test_switching_variant_changes_the_blocks(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    assert len(manifest.soundtrack.variants) > 1
    first = screen.editor.description.toPlainText()

    screen.variant_box.setCurrentIndex(1)

    assert screen.editor.description.toPlainText() != first
    assert manifest.soundtrack.chosen_variant == 1


def test_setting_the_bpm_regenerates_and_records_it(screen: SoundtrackScreen) -> None:
    """The scenario from the spec: 124 in the Description and 124 on the manifest."""
    manifest = screen._state.manifest
    assert manifest is not None

    screen.bpm_field.setValue(124)
    screen.bpm_field.editingFinished.emit()

    assert "124 bpm" in screen.editor.description.toPlainText()
    assert manifest.soundtrack.proposed_bpm == 124


def test_choosing_a_genre_row_overrules_the_match(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    wanted = "reggae and dub"

    screen.genre_box.setCurrentIndex(screen.genre_box.findData(wanted))

    assert manifest.soundtrack.matched_row == wanted
    assert "reggae dub" in screen.editor.description.toPlainText()


# --- the mood controls --------------------------------------------------------


def test_calmer_changes_the_mood_words_and_not_the_genre(screen: SoundtrackScreen) -> None:
    """The scenario from the spec."""
    manifest = screen._state.manifest
    assert manifest is not None
    genre = manifest.soundtrack.genre
    before = screen.editor.description.toPlainText()

    screen.mood_box.setCurrentIndex(0)  # calmer

    after = screen.editor.description.toPlainText()
    assert after != before
    assert manifest.soundtrack.genre == genre
    assert after.startswith(str(genre))


def test_the_room_control_also_stays_inside_the_row(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    genre = manifest.soundtrack.genre

    screen.room_box.setCurrentIndex(0)  # intimate

    assert manifest.soundtrack.genre == genre
    assert screen.editor.description.toPlainText().startswith(str(genre))


def test_a_moved_mood_still_validates(screen: SoundtrackScreen) -> None:
    for index in (0, 2):
        screen.mood_box.setCurrentIndex(index)
        assert screen.editor.revalidate() == [], index


def test_as_matched_goes_back_to_the_row_s_own_mood(screen: SoundtrackScreen) -> None:
    """A control that could not be put back would not be a control."""
    original = screen.editor.description.toPlainText()

    screen.mood_box.setCurrentIndex(2)  # more energetic
    moved = screen.editor.description.toPlainText()
    screen.mood_box.setCurrentIndex(1)  # as matched

    assert moved != original
    assert screen.editor.description.toPlainText() == original


def test_two_moves_in_a_row_are_not_two_moves(screen: SoundtrackScreen) -> None:
    """Each position is absolute: the pool is the row's, not the last result's."""
    screen.mood_box.setCurrentIndex(0)
    once = screen.editor.description.toPlainText()

    screen.mood_box.setCurrentIndex(1)
    screen.mood_box.setCurrentIndex(0)

    assert screen.editor.description.toPlainText() == once


def test_the_mood_control_leaves_a_hand_written_prompt_alone(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    screen.editor.title.setText("Mine")
    assert screen.store_edit()
    mine = manifest.soundtrack.variants[0].description

    screen.mood_box.setCurrentIndex(0)

    assert manifest.soundtrack.variants[0].source == "user"
    assert manifest.soundtrack.variants[0].description == mine


# --- hand editing -------------------------------------------------------------


def test_the_screen_says_a_hand_edit_was_left_alone(screen: SoundtrackScreen) -> None:
    """Doing nothing silently reads as a broken control, so the screen says why."""
    screen.editor.title.setText("Mine")
    assert screen.store_edit()

    screen.mood_box.setCurrentIndex(0)

    assert "Your edit is unchanged" in screen.editor.problems.text()


def test_both_mood_axes_are_labelled_by_their_ends(screen: SoundtrackScreen) -> None:
    """ "Mood" and "Room" said neither which way the control goes nor what it does."""
    labels = [child.text() for child in screen.findChildren(type(screen.matched_label))]

    assert "Calm to energetic" in labels
    assert "Intimate to cinematic" in labels
    assert "Room" not in labels


def test_a_comma_in_a_tag_is_marked_on_its_line(screen: SoundtrackScreen) -> None:
    """The scenario from the spec, with the line number the validator reported."""
    lines = screen.editor.structure_lines()
    lines[1] = "[slow, dark intro]"
    screen.editor.structure.setPlainText("\n".join(lines))

    violations = screen.editor.revalidate()

    assert violations
    assert any("comma" in violation.rule for violation in violations)
    assert any(violation.line == 2 for violation in violations)
    assert "line 2" in screen.editor.problems.text()
    assert not screen.editor.ok


def test_an_invalid_structure_asks_before_copying(
    screen: SoundtrackScreen, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autocut.gui.widgets import prompt_editor as module

    asked: list[str] = []
    monkeypatch.setattr(
        module.QMessageBox,
        "question",
        lambda _parent, title, _text: asked.append(title) or module.QMessageBox.StandardButton.No,
    )
    screen.editor.structure.setPlainText("[slow, dark intro]\n[end]")
    screen.editor.revalidate()

    copied = screen.editor.copy("Structure")

    assert asked == ["Copy anyway?"]
    assert copied is False


def test_a_valid_edit_is_stored_as_the_users_own(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    screen.editor.title.setText("A Title Of My Own")

    assert screen.store_edit()

    assert manifest.soundtrack.variants[0].source == "user"
    assert manifest.soundtrack.variants[0].title == "A Title Of My Own"
    assert screen.variant_box.itemText(0).endswith("(yours)")


def test_an_invalid_edit_is_refused_with_the_reason(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    before = list(manifest.soundtrack.variants)
    screen.editor.structure.setPlainText("[slow, dark intro]\n[end]")

    assert screen.store_edit() is False

    assert manifest.soundtrack.variants == before
    assert "Not kept" in screen.editor.problems.text()


def test_the_valid_message_says_it_is_ready(screen: SoundtrackScreen) -> None:
    screen.editor.revalidate()

    assert "ready to paste" in screen.editor.problems.text()


def test_writing_the_prompt_file(screen: SoundtrackScreen) -> None:
    written: list[str] = []
    screen.prompt_written.connect(written.append)

    path = screen.write_file()

    assert path is not None
    assert path.name == "suno-prompt.md"
    text = path.read_text(encoding="utf-8")
    assert "**Description**" in text
    assert written == [str(path)]


def test_the_prompt_file_opens_with_the_hand_written_variant(screen: SoundtrackScreen) -> None:
    screen.editor.title.setText("Mine First")
    assert screen.store_edit()

    path = screen.write_file()

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "yours, edited by hand" in text
    assert text.index("Mine First") < text.index("Variant 2")


def test_the_refinement_note_says_why_it_is_off(screen: SoundtrackScreen) -> None:
    assert "Refinement is off" in screen.refine_note.text()


# --- the track ----------------------------------------------------------------


@pytest.mark.ffmpeg
def test_loading_the_click_fixture_measures_and_draws_it(
    screen: SoundtrackScreen, synthetic_dir: Path
) -> None:
    manifest = screen._state.manifest
    assert manifest is not None

    assert screen.load_track(synthetic_dir / CLICK)

    assert "measured 120 bpm" in screen.track_label.text()
    assert screen.waveform.beat_count > 20
    assert manifest.soundtrack.measured_bpm == pytest.approx(120.0, abs=1.0)
    assert manifest.soundtrack.audio_path == synthetic_dir / CLICK
    assert screen.apply_button.isEnabled()


@pytest.mark.ffmpeg
def test_the_comparison_warns_and_offers_the_proposed_bpm(
    screen: SoundtrackScreen, synthetic_dir: Path
) -> None:
    """The drifted scenario: both numbers shown, and the override field offers the fix."""
    manifest = screen._state.manifest
    assert manifest is not None
    manifest.soundtrack.proposed_bpm = 126.0

    screen.load_track(synthetic_dir / CLICK)

    assert manifest.soundtrack.comparison == "drifted"
    assert "126" in screen.comparison_label.text()
    assert "120" in screen.comparison_label.text()


@pytest.mark.ffmpeg
def test_a_half_tempo_reading_pre_fills_the_override(
    screen: SoundtrackScreen, synthetic_dir: Path
) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    manifest.soundtrack.proposed_bpm = 240.0

    screen.load_track(synthetic_dir / CLICK)

    assert manifest.soundtrack.comparison == "half"
    assert screen.override_field.value() == pytest.approx(240.0)
    assert screen.effective_bpm() == pytest.approx(240.0)


@pytest.mark.ffmpeg
def test_the_override_is_what_apply_would_use(
    screen: SoundtrackScreen, synthetic_dir: Path
) -> None:
    screen.load_track(synthetic_dir / CLICK)

    screen.override_field.setValue(100.0)

    assert screen.effective_bpm() == pytest.approx(100.0)
    assert "At 100 bpm" in screen.distribution_label.text()


@pytest.mark.ffmpeg
def test_the_preview_shows_the_distribution_without_syncing(
    screen: SoundtrackScreen, synthetic_dir: Path
) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    screen.load_track(synthetic_dir / CLICK)

    text = screen.distribution_label.text()

    assert "beats per clip" in text
    assert "becomes" in text
    # A preview touches nothing: no segment has a beat count yet.
    assert all(segment.beats is None for segment in manifest.segments.values())


@pytest.mark.ffmpeg
def test_apply_sync_sets_the_final_bounds_and_the_beat_map(
    screen: SoundtrackScreen, synthetic_dir: Path, qtbot: Any
) -> None:
    """The apply scenario from the spec."""
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    screen.load_track(synthetic_dir / CLICK)
    synced: list[int] = []
    screen.synced.connect(lambda: synced.append(1))

    with qtbot.waitSignal(state.stage_finished, timeout=30_000):
        assert screen.apply_sync()

    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    assert selected
    assert all(segment.beats is not None for segment in selected)
    assert all(segment.final_start_s is not None for segment in selected)
    assert manifest.soundtrack.beatmap_path is not None
    assert Path(manifest.soundtrack.beatmap_path).exists()
    assert synced == [1]
    assert "Synced" in screen.distribution_label.text()


@pytest.mark.ffmpeg
def test_apply_records_the_override(
    screen: SoundtrackScreen, synthetic_dir: Path, qtbot: Any
) -> None:
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    screen.load_track(synthetic_dir / CLICK)
    screen.override_field.setValue(124.0)

    with qtbot.waitSignal(state.stage_finished, timeout=30_000):
        assert screen.apply_sync()

    assert manifest.soundtrack.bpm_override == pytest.approx(124.0)
    segment = next(s for s in manifest.segments.values() if s.outcome == "selected")
    assert segment.beats is not None
    assert segment.target_duration_s == pytest.approx(segment.beats * 60 / 124)


@pytest.mark.ffmpeg
def test_a_track_that_will_not_decode_says_so(screen: SoundtrackScreen, tmp_path: Path) -> None:
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not audio")

    assert screen.load_track(broken) is False

    assert "could not decode" in screen.track_label.text()
    assert not screen.apply_button.isEnabled()


def test_nothing_is_editable_while_a_stage_runs(screen: SoundtrackScreen, qtbot: Any) -> None:
    import threading

    state = screen._state
    gate = threading.Event()
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))
    qtbot.wait(30)

    assert not screen.generate_button.isEnabled()
    assert not screen.write_button.isEnabled()
    assert not screen.editor.isEnabled()
    assert screen.write_file() is None
    assert screen.store_edit() is False

    gate.set()
    with qtbot.waitSignal(state.stage_finished, timeout=5000):
        pass
    # The signal comes from inside the thread's run, so the thread is still winding
    # down: a QThread collected while running makes Qt abort the process.
    assert state.wait_for_stage(10_000)
    assert screen.generate_button.isEnabled()


# --- play with track ----------------------------------------------------------


def test_play_with_track_is_off_until_a_sync_has_run(screen: SoundtrackScreen) -> None:
    """Hearing the cuts is the point, and before a sync the clips are not on the grid."""
    assert not screen.play_with_track_button.isEnabled()
    assert screen.play_with_track() is False


@pytest.mark.ffmpeg
def test_play_with_track_renders_the_montage_with_audio(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path
) -> None:
    """The scenario from the spec: after Apply sync, the montage plays with the track."""
    from tests.unit.test_montage import CLIPS
    from tests.unit.test_montage import project as montage_manifest

    manifest = montage_manifest(tmp_path, CLIPS, synthetic_dir)
    manifest.save(tmp_path / "edit" / "manifest.json")
    state = ProjectState()
    state.open_project(tmp_path / "edit")
    state.config.cache.dir = tmp_path / "cache"
    screen = SoundtrackScreen(state)
    qtbot.addWidget(screen)
    assert screen.generate()
    assert screen.load_track(synthetic_dir / CLICK)

    with qtbot.waitSignal(state.stage_finished, timeout=60_000):
        assert screen.apply_sync()
    assert state.wait_for_stage(10_000)
    assert screen.play_with_track_button.isEnabled()

    with qtbot.waitSignal(state.stage_finished, timeout=180_000) as blocker:
        assert screen.play_with_track()
    assert state.wait_for_stage(10_000)

    assert blocker.args == ["montage"]
    opened = state.manifest
    assert opened is not None
    assert opened.preview.has_audio
    # isHidden rather than isVisible: the screen itself is never shown in a test, and
    # a child of a hidden parent is not visible however it was set.
    assert not screen.montage.isHidden()
    assert screen.montage.path is not None
    assert len(screen.montage.parts) == 3
    # The track is in the file, which is the whole reason for this button.
    from tests.unit.test_montage import _streams

    kinds = [stream["codec_type"] for stream in _streams(screen.montage.path)]
    assert kinds.count("audio") == 1
    assert kinds.count("video") == 1


@pytest.mark.ffmpeg
def test_a_sync_that_fails_leaves_play_with_track_off(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loaded track is not enough: without a finished sync there is nothing to hear."""
    from autocut.gui.screens import soundtrack as module
    from tests.unit.test_montage import CLIPS
    from tests.unit.test_montage import project as montage_manifest

    manifest = montage_manifest(tmp_path, CLIPS, synthetic_dir)
    manifest.save(tmp_path / "edit" / "manifest.json")
    state = ProjectState()
    state.open_project(tmp_path / "edit")
    state.config.cache.dir = tmp_path / "cache"
    screen = SoundtrackScreen(state)
    qtbot.addWidget(screen)
    assert screen.generate()
    assert screen.load_track(synthetic_dir / CLICK)
    assert not screen.play_with_track_button.isEnabled()

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the beat grid fell over")

    monkeypatch.setattr(module, "quantize_durations", explode)
    with qtbot.waitSignal(state.error, timeout=30_000) as blocker:
        assert screen.apply_sync()
    assert state.wait_for_stage(10_000)

    assert "fell over" in blocker.args[0]
    opened = state.manifest
    assert opened is not None
    assert all(segment.beats is None for segment in opened.segments.values())
    assert not screen.play_with_track_button.isEnabled()
    assert screen.play_with_track() is False
    # The rest of the screen comes back: a failed stage emits neither finished nor
    # cancelled, and the screen used to stay disabled until the next one ran.
    assert screen.generate_button.isEnabled()
    assert screen.apply_button.isEnabled()


@pytest.mark.ffmpeg
def test_a_cancelled_sync_leaves_play_with_track_off(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path
) -> None:
    from tests.unit.test_montage import CLIPS
    from tests.unit.test_montage import project as montage_manifest

    manifest = montage_manifest(tmp_path, CLIPS, synthetic_dir)
    manifest.save(tmp_path / "edit" / "manifest.json")
    state = ProjectState()
    state.open_project(tmp_path / "edit")
    state.config.cache.dir = tmp_path / "cache"
    screen = SoundtrackScreen(state)
    qtbot.addWidget(screen)
    assert screen.generate()
    assert screen.load_track(synthetic_dir / CLICK)

    state.cancel()  # cleared by run_stage, so the sync still finishes
    with qtbot.waitSignal(state.stage_finished, timeout=30_000):
        assert screen.apply_sync()
    assert state.wait_for_stage(10_000)

    # A stale cancel does not stop a run, so this one synced and the button is on.
    assert screen.play_with_track_button.isEnabled()


@pytest.mark.ffmpeg
def test_the_transport_names_the_clip_by_its_file_and_time(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path
) -> None:
    """The label showed a content hash, which identifies the clip and says nothing."""
    from autocut.gui.widgets.montage import clip_labels
    from tests.unit.test_montage import CLIPS
    from tests.unit.test_montage import project as montage_manifest

    manifest = montage_manifest(tmp_path, CLIPS, synthetic_dir)
    labels = clip_labels(manifest)

    assert set(labels) == set(manifest.segments)
    for segment_id, label in labels.items():
        assert label.endswith(" s")
        assert ".mp4" in label
        assert segment_id.split(":")[0] not in label


@pytest.mark.ffmpeg
def test_a_second_play_with_track_renders_nothing(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path
) -> None:
    from tests.unit.test_montage import CLIPS
    from tests.unit.test_montage import project as montage_manifest

    manifest = montage_manifest(tmp_path, CLIPS, synthetic_dir)
    manifest.save(tmp_path / "edit" / "manifest.json")
    state = ProjectState()
    state.open_project(tmp_path / "edit")
    state.config.cache.dir = tmp_path / "cache"
    screen = SoundtrackScreen(state)
    qtbot.addWidget(screen)
    assert screen.generate()
    screen.load_track(synthetic_dir / CLICK)
    with qtbot.waitSignal(state.stage_finished, timeout=60_000):
        screen.apply_sync()
    state.wait_for_stage(10_000)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        screen.play_with_track()
    state.wait_for_stage(10_000)
    opened = state.manifest
    assert opened is not None and opened.preview.path is not None
    built = Path(opened.preview.path)
    stamp = built.stat().st_mtime_ns

    assert screen.play_with_track()

    assert not state.is_running
    assert built.stat().st_mtime_ns == stamp


# --- issue 43: a sync that is applied, and one that only looks applied ---------


def synced_project(tmp_path: Path, synthetic_dir: Path) -> ProjectState:
    from tests.unit.test_montage import CLIPS
    from tests.unit.test_montage import project as montage_manifest

    manifest = montage_manifest(tmp_path, CLIPS, synthetic_dir)
    # Lengths that are not already whole beats at 120, or quantising would have nothing
    # to move and the test would prove nothing about the sync.
    for index, segment in enumerate(manifest.segments.values()):
        segment.target_duration_s = 1.3 + index * 0.2
    manifest.save(tmp_path / "edit" / "manifest.json")
    state = ProjectState()
    state.open_project(tmp_path / "edit")
    state.config.cache.dir = tmp_path / "cache"
    return state


@pytest.mark.ffmpeg
def test_apply_sync_moves_the_bounds_and_the_fingerprint(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path
) -> None:
    """The heart of issue 43: a sync has to change the clips, not only the numbers."""
    from autocut.core.montage import montage_fingerprint

    state = synced_project(tmp_path, synthetic_dir)
    screen = SoundtrackScreen(state)
    qtbot.addWidget(screen)
    assert screen.generate()
    track = synthetic_dir / CLICK
    assert screen.load_track(track)
    manifest = state.manifest
    assert manifest is not None
    before_fingerprint = montage_fingerprint(manifest, state.config, track)
    before = {
        segment.id: (segment.final_start_s, segment.final_end_s, segment.target_duration_s)
        for segment in manifest.segments.values()
        if segment.outcome == "selected"
    }
    assert all(bounds[0] is None for bounds in before.values())

    with qtbot.waitSignal(state.stage_finished, timeout=60_000):
        assert screen.apply_sync()
    assert state.wait_for_stage(10_000)

    after = {
        segment.id: (segment.final_start_s, segment.final_end_s, segment.target_duration_s)
        for segment in manifest.segments.values()
        if segment.outcome == "selected"
    }
    assert all(bounds[0] is not None for bounds in after.values())
    assert after != before
    assert montage_fingerprint(manifest, state.config, track) != before_fingerprint
    # And it is on disk, not only in memory.
    saved = Manifest.load(tmp_path / "edit" / "manifest.json")
    for segment_id, bounds in after.items():
        assert saved.segments[segment_id].final_start_s == pytest.approx(bounds[0])
    assert saved.soundtrack.synced_bpm == pytest.approx(screen.effective_bpm())
    assert saved.soundtrack.synced_audio_path == track


@pytest.mark.ffmpeg
def test_a_newly_loaded_track_is_not_a_synced_one(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path
) -> None:
    """What the user actually hit: yesterday's beats made today's track look synced.

    The project is synced to one track, another is loaded, and the clips are still cut
    to the first. Every clip carries beats, so the old test for "synced" said yes and
    the montage went out with the new music over the old cuts.
    """
    state = synced_project(tmp_path, synthetic_dir)
    screen = SoundtrackScreen(state)
    qtbot.addWidget(screen)
    assert screen.generate()
    assert screen.load_track(synthetic_dir / CLICK)
    with qtbot.waitSignal(state.stage_finished, timeout=60_000):
        assert screen.apply_sync()
    assert state.wait_for_stage(10_000)
    assert screen.play_with_track_button.isEnabled()
    manifest = state.manifest
    assert manifest is not None
    assert all(
        segment.beats is not None
        for segment in manifest.segments.values()
        if segment.outcome == "selected"
    )

    other = tmp_path / "other.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=6",
            str(other),
        ],
        check=True,
    )
    assert screen.load_track(other)

    # Still carrying beats, and no longer synced: the track under them is not this one.
    assert not screen._synced_with_a_track()
    assert not screen.play_with_track_button.isEnabled()
    assert screen.play_with_track() is False
    assert "Apply sync first" in screen.distribution_label.text()


@pytest.mark.ffmpeg
def test_a_changed_tempo_is_not_a_synced_one(
    qtbot: Any, tmp_path: Path, synthetic_dir: Path
) -> None:
    """The same track at another tempo is another set of bounds."""
    state = synced_project(tmp_path, synthetic_dir)
    screen = SoundtrackScreen(state)
    qtbot.addWidget(screen)
    assert screen.generate()
    assert screen.load_track(synthetic_dir / CLICK)
    with qtbot.waitSignal(state.stage_finished, timeout=60_000):
        assert screen.apply_sync()
    assert state.wait_for_stage(10_000)

    screen.override_field.setValue(96.0)

    assert screen.effective_bpm() == pytest.approx(96.0)
    assert not screen._synced_with_a_track()


# --- the waveform widget ------------------------------------------------------


def test_the_waveform_says_when_there_is_no_track(qtbot: Any) -> None:
    view = WaveformView()
    qtbot.addWidget(view)
    view.resize(400, 120)

    assert view.beat_count == 0
    # Painting an empty view must not raise, which is what a grab exercises.
    assert not view.grab().toImage().isNull()


def test_the_waveform_draws_an_envelope_and_its_beats(qtbot: Any) -> None:
    view = WaveformView()
    qtbot.addWidget(view)
    view.resize(400, 120)
    pairs = np.stack(
        [-np.abs(np.sin(np.linspace(0, 6, 500))), np.abs(np.sin(np.linspace(0, 6, 500)))],
        axis=1,
    ).astype(np.float32)

    view.set_track(pairs, [0.5, 1.0, 1.5], 2.0)

    assert view.beat_count == 3
    assert not view.grab().toImage().isNull()
    assert view.time_at(200) == pytest.approx(1.0, abs=0.05)


def test_clicking_the_waveform_reports_the_time(qtbot: Any) -> None:
    view = WaveformView()
    qtbot.addWidget(view)
    view.resize(400, 120)
    view.set_track(np.zeros((10, 2), dtype=np.float32), [], 8.0)
    seen: list[float] = []
    view.clicked_time.connect(seen.append)

    view.set_cursor(view.time_at(100))
    view.clicked_time.emit(view.time_at(100))

    assert seen == [pytest.approx(2.0, abs=0.1)]


def test_the_envelope_is_cached_beside_the_manifest(tmp_path: Path) -> None:
    audio = tmp_path / "track.wav"
    audio.write_bytes(b"pretend")
    samples = np.sin(np.linspace(0, 50, 10_000)).astype(np.float32)

    first = load_or_build_envelope(samples, tmp_path, audio, points=100)
    path = envelope_path(tmp_path, audio)
    second = load_or_build_envelope(np.zeros(10_000, dtype=np.float32), tmp_path, audio, 100)

    assert path.exists()
    assert first.shape == (100, 2)
    # The second call read the cache rather than the samples it was handed.
    assert np.allclose(first, second)


def test_a_replaced_track_gets_a_new_cache_key(tmp_path: Path) -> None:
    """The key is size and mtime, so a track swapped under the same name is not reused."""
    audio = tmp_path / "track.wav"
    audio.write_bytes(b"first")
    first = envelope_path(tmp_path, audio)

    audio.write_bytes(b"a longer second take")
    second = envelope_path(tmp_path, audio)

    assert first != second


# --- the editor on its own ----------------------------------------------------


def test_the_editor_reports_no_violations_on_an_empty_prompt(qtbot: Any, tmp_path: Path) -> None:
    """An empty editor is not a valid prompt, and it must not pretend otherwise."""
    from autocut.core.config import AutocutConfig

    editor = PromptEditor(AutocutConfig())
    qtbot.addWidget(editor)

    violations = editor.revalidate()

    assert violations
    assert not editor.ok
    assert editor.copy("Description") is False


def test_the_editor_round_trips_a_variant(screen: SoundtrackScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    original = manifest.soundtrack.variants[0]

    back = screen.editor.as_variant()

    assert back.title == original.title
    assert back.description == original.description
    assert back.structure == original.structure
    assert back.instruments == original.instruments
    assert back.source == "user"


def test_the_screen_follows_another_project(screen: SoundtrackScreen, tmp_path: Path) -> None:
    other = reviewable(tmp_path, tmp_path / "other", clips=6)
    state = screen._state

    state.open_project(tmp_path / "other")

    assert other.manifest is not None
    assert screen.variant_box.count() == 0
    assert "Generate the prompt" in screen.matched_label.text()


def test_an_empty_state_says_so(qtbot: Any) -> None:
    widget = SoundtrackScreen(ProjectState())
    qtbot.addWidget(widget)

    assert "Open a project" in widget.matched_label.text()
    assert widget.variant_box.count() == 0


def test_the_manifest_keeps_the_track_across_a_reload(
    screen: SoundtrackScreen, tmp_path: Path
) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    screen._state.save_now()

    reloaded = Manifest.load(tmp_path / "edit" / "manifest.json")

    assert reloaded.soundtrack.matched_row == manifest.soundtrack.matched_row
    assert len(reloaded.soundtrack.variants) == len(manifest.soundtrack.variants)

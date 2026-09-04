"""The Export screen: the options, the dry run, the run itself and the stale files."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from autocut.core.config import AutocutConfig  # noqa: E402
from autocut.core.export import ExportResult  # noqa: E402
from autocut.core.naming import SELECTS_DIR, STALE_DIR  # noqa: E402
from autocut.gui.screens.export import ExportScreen, folder_size  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from tests.unit.test_gui_review import reviewable  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def screen(qtbot: Any, tmp_path: Path) -> ExportScreen:
    state = reviewable(tmp_path, tmp_path / "edit")
    widget = ExportScreen(state)
    qtbot.addWidget(widget)
    widget.resize(1000, 900)
    return widget


def read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


# --- the options --------------------------------------------------------------


def test_the_fields_start_from_the_configuration(screen: ExportScreen) -> None:
    export = screen._state.config.export

    assert screen.mode_box.currentText() == export.mode
    assert screen.codec_box.currentText() == export.codec
    assert screen.crf_field.value() == export.crf
    assert screen.width_field.value() == export.max_width
    assert screen.vertical_box.currentText() == export.vertical_strategy
    # "auto" is the zero position of the fps field, not a value.
    assert screen.fps_field.value() == 0.0


def test_the_audio_box_asks_the_question_a_person_has(screen: ExportScreen) -> None:
    """The config says whether to remove the audio; the screen asks whether to keep it."""
    export = screen._state.config.export

    for source_class in ("drone", "phone"):
        assert screen.audio_boxes[source_class].isChecked() == (
            not export.remove_audio.get(source_class)
        )


def test_keeping_phone_audio_lands_in_the_config_and_the_file(screen: ExportScreen) -> None:
    """The scenario from the spec."""
    state = screen._state
    assert state.config.export.remove_audio.get("phone")

    screen.audio_boxes["phone"].setChecked(True)

    assert state.config.export.remove_audio.get("phone") is False
    path = state.config_path
    assert path is not None
    assert read_toml(path)["export"]["remove_audio"]["phone"] is False


def test_the_next_export_would_keep_that_audio(screen: ExportScreen) -> None:
    """The point of writing the file: the CLI reads the same project."""
    state = screen._state
    screen.audio_boxes["phone"].setChecked(True)
    path = state.config_path
    assert path is not None

    reloaded = AutocutConfig.load(path)

    assert reloaded.export.remove_audio.get("phone") is False


def test_the_mode_and_the_codec_are_written(screen: ExportScreen) -> None:
    state = screen._state

    screen.mode_box.setCurrentText("fast")
    screen.codec_box.setCurrentText("libx265")
    screen.crf_field.setValue(22)

    path = state.config_path
    assert path is not None
    written = read_toml(path)["export"]
    assert written["mode"] == "fast"
    assert written["codec"] == "libx265"
    assert written["crf"] == 22
    assert state.config.export.mode == "fast"


def test_the_fps_field_writes_auto_as_auto(screen: ExportScreen) -> None:
    state = screen._state

    screen.fps_field.setValue(30.0)
    screen.fps_field.setValue(0.0)

    assert state.config.export.fps == "auto"
    path = state.config_path
    assert path is not None
    assert read_toml(path)["export"]["fps"] == "auto"


def test_a_lut_path_is_written_per_class(screen: ExportScreen, tmp_path: Path) -> None:
    lut = tmp_path / "drone.cube"
    lut.write_text("LUT", encoding="utf-8")
    state = screen._state

    screen.lut_fields["drone"].setText(str(lut))

    assert state.config.export.lut.get("drone") == lut
    path = state.config_path
    assert path is not None
    assert read_toml(path)["export"]["lut"]["drone"] == str(lut)


def test_the_slow_motion_and_lens_boxes_are_per_class(screen: ExportScreen) -> None:
    state = screen._state

    screen.slow_boxes["reflex"].setChecked(True)
    screen.lens_boxes["drone"].setChecked(True)

    assert state.config.export.slow_motion_auto.get("reflex") is True
    assert state.config.export.lens_correction.get("drone") is True


def test_the_manifest_snapshot_follows_the_options(screen: ExportScreen) -> None:
    screen.crf_field.setValue(25)

    manifest = screen._state.manifest
    assert manifest is not None
    assert manifest.config_snapshot["export"]["crf"] == 25


# --- the dry run --------------------------------------------------------------


def test_the_plan_says_what_the_export_would_do(screen: ExportScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]

    text = screen.plan_label.text()

    assert f"{len(selected)} clips" in text
    assert "fps" in text
    assert "precise cut" in text
    assert "No beat sync yet" in text


def test_the_plan_notices_the_beat_grid(screen: ExportScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    for segment in manifest.segments.values():
        if segment.outcome == "selected":
            segment.beats = 4

    screen.refresh_plan()

    assert "cut to the beat grid" in screen.plan_label.text()


def test_the_plan_follows_the_mode(screen: ExportScreen) -> None:
    screen.mode_box.setCurrentText("fast")

    assert "fast cut" in screen.plan_label.text()


def test_nothing_selected_disables_the_run(screen: ExportScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    for segment in manifest.segments.values():
        segment.outcome = "candidate"
        segment.order = None

    screen.refresh_plan()

    assert not screen.run_button.isEnabled()
    assert "Nothing is selected" in screen.plan_label.text()


def test_an_empty_state_says_to_open_a_project(qtbot: Any) -> None:
    widget = ExportScreen(ProjectState())
    qtbot.addWidget(widget)

    assert "Open a project first" in widget.plan_label.text()
    assert not widget.run_button.isEnabled()


# --- running ------------------------------------------------------------------


@pytest.fixture
def real_clips(tmp_path: Path, synthetic_dir: Path, qtbot: Any) -> ExportScreen:
    """A project over the synthetic clips, analysed and selected, ready to export."""
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"
    widget = ExportScreen(state)
    qtbot.addWidget(widget)
    from autocut.core.analyze import analyze_files
    from autocut.core.ingest import ingest

    files = ingest([synthetic_dir], state.config)
    manifest = state.manifest
    assert manifest is not None
    manifest.files = {source.id: source for source in files}
    analyze_files(manifest, state.config)
    state.config.selection.max_clips = 3
    state.run_selection()
    widget.reload()
    return widget


@pytest.mark.ffmpeg
def test_an_export_writes_the_clips_and_summarises(real_clips: ExportScreen, qtbot: Any) -> None:
    screen = real_clips
    state = screen._state

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert screen.run()

    result = state.last_result
    assert isinstance(result, ExportResult)
    assert result.exported >= 1
    assert result.failed == 0
    assert "clips written" in screen.summary.text()
    assert "MB in" in screen.summary.text()
    selects = screen.selects_dir()
    assert selects is not None
    assert list(selects.glob("*.mp4"))


@pytest.mark.ffmpeg
def test_a_second_export_skips_everything(real_clips: ExportScreen, qtbot: Any) -> None:
    """The scenario from the spec: nothing changed, so nothing is written again."""
    screen = real_clips
    state = screen._state
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        screen.run()
    first = state.last_result
    assert isinstance(first, ExportResult)

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        screen.run()
    second = state.last_result

    assert isinstance(second, ExportResult)
    assert second.skipped == first.exported + first.skipped
    assert second.exported == 0
    assert f"{second.skipped} unchanged and skipped" in screen.summary.text()


@pytest.mark.ffmpeg
def test_one_unreadable_source_is_listed_and_the_others_are_written(
    real_clips: ExportScreen, qtbot: Any, tmp_path: Path
) -> None:
    """The scenario from the spec: the run completes and names the clip that failed."""
    screen = real_clips
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    assert len(selected) >= 2
    broken = manifest.files[selected[0].file_id]
    broken.path = tmp_path / "gone.mp4"

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert screen.run()

    result = state.last_result
    assert isinstance(result, ExportResult)
    assert result.failed == 1
    assert result.exported == len(selected) - 1
    assert screen.describe_problems(result)
    assert selected[0].id in screen.describe_problems(result)
    assert "1 failed" in screen.summary.text()


@pytest.mark.ffmpeg
def test_the_progress_bar_follows_the_clips(real_clips: ExportScreen, qtbot: Any) -> None:
    screen = real_clips
    state = screen._state
    seen: list[int] = []

    def watch(event: Any) -> None:
        if getattr(event, "stage", "") == "export":
            seen.append(event.current)

    state.progress.connect(watch)

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        screen.run()

    assert seen == sorted(seen)
    assert screen.bar.value() == screen.bar.maximum()
    assert screen.current_label.text() == "Finished"


def test_nothing_is_editable_while_a_stage_runs(screen: ExportScreen, qtbot: Any) -> None:
    import threading

    state = screen._state
    gate = threading.Event()
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))
    qtbot.wait(30)

    assert not screen.run_button.isEnabled()
    assert not screen.mode_box.isEnabled()
    assert screen.cancel_button.isEnabled()
    assert screen.run() is False

    gate.set()
    with qtbot.waitSignal(state.stage_finished, timeout=5000):
        pass
    # The signal comes from inside the thread's run, so the thread is still winding
    # down: a QThread collected while running makes Qt abort the process.
    assert state.wait_for_stage(10_000)
    assert screen.run_button.isEnabled()
    assert not screen.cancel_button.isEnabled()


# --- the folder and the stale files -------------------------------------------


def test_stale_files_are_counted_and_offered(screen: ExportScreen) -> None:
    """The scenario from the spec: three clips dropped, three stale files, deletion offered."""
    selects = screen.selects_dir()
    assert selects is not None
    stale = selects / STALE_DIR
    stale.mkdir(parents=True)
    for index in range(3):
        (stale / f"old_{index}.mp4").write_bytes(b"stale")

    screen.refresh_stale()

    assert screen.stale_button.isEnabled()
    assert screen.stale_button.text() == "Delete 3 stale files"
    assert len(screen.stale_files()) == 3


def test_deleting_the_stale_files_removes_only_those(screen: ExportScreen) -> None:
    selects = screen.selects_dir()
    assert selects is not None
    stale = selects / STALE_DIR
    stale.mkdir(parents=True)
    (stale / "old.mp4").write_bytes(b"stale")
    kept = selects / "001_clip.mp4"
    kept.write_bytes(b"current")
    nested = stale / "deeper"
    nested.mkdir()
    (nested / "not_mine.mp4").write_bytes(b"someone else's")

    removed = screen.delete_stale(confirm=False)

    assert removed == 1
    assert not (stale / "old.mp4").exists()
    assert kept.exists()
    # Only files directly under _stale/: this is a delete button in the user's folder.
    assert (nested / "not_mine.mp4").exists()
    assert not screen.stale_button.isEnabled()


def test_deleting_asks_first(screen: ExportScreen, monkeypatch: pytest.MonkeyPatch) -> None:
    from autocut.gui.screens import export as module

    selects = screen.selects_dir()
    assert selects is not None
    stale = selects / STALE_DIR
    stale.mkdir(parents=True)
    (stale / "old.mp4").write_bytes(b"stale")
    asked: list[str] = []
    monkeypatch.setattr(
        module.QMessageBox,
        "question",
        lambda _parent, title, _text: asked.append(title) or module.QMessageBox.StandardButton.No,
    )

    removed = screen.delete_stale()

    assert asked == ["Delete the stale files?"]
    assert removed == 0
    assert (stale / "old.mp4").exists()


def test_no_stale_files_means_nothing_to_delete(screen: ExportScreen) -> None:
    assert screen.stale_files() == []
    assert screen.delete_stale(confirm=False) == 0
    assert not screen.stale_button.isEnabled()


def test_opening_the_folder_before_an_export_says_so(screen: ExportScreen) -> None:
    assert screen.open_folder() is False
    assert "Nothing exported yet" in screen.problems.text()


def test_the_folder_size_ignores_what_it_cannot_read(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"1234")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.mp4").write_bytes(b"12345")

    assert folder_size(tmp_path) == 9
    assert folder_size(tmp_path / "nowhere") == 0


def test_the_summary_names_the_selects_folder(screen: ExportScreen) -> None:
    result = ExportResult(
        target_fps=25.0,
        exported=3,
        skipped=1,
        failed=0,
        slow_motion=1,
        fps_converted=2,
        stale_moved=3,
        selects_dir=screen.selects_dir(),
    )

    text = screen.describe(result)

    assert "3 clips written, 1 unchanged and skipped, 0 failed" in text
    assert "25 fps, 1 slowed down, 2 resampled" in text
    assert f"3 stale files moved to {STALE_DIR}" in text
    assert SELECTS_DIR in text

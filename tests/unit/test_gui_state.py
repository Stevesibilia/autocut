"""``ProjectState``: opening, autosaving, and being the only thing that runs a stage."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from autocut.core.events import ProgressCallback, ProgressEvent  # noqa: E402
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile  # noqa: E402
from autocut.gui.state import AUTOSAVE_DEBOUNCE_MS, ProjectState  # noqa: E402

pytestmark = pytest.mark.gui


def a_manifest(out: Path, clips: int = 4, selected: bool = False) -> Manifest:
    """A project with probed files and scored segments, without running any stage."""
    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[out], output_dir=out)
    for index in range(clips):
        file_id = f"f{index}"
        manifest.files[file_id] = SourceFile(
            id=file_id,
            path=out / f"{file_id}.MP4",
            source_class="actioncam",
            duration_s=60.0,
            width=1920,
            height=1080,
            fps=25.0,
            codec="h264",
            pix_fmt="yuv420p",
        )
        manifest.segments[f"{file_id}:0"] = Segment(
            id=f"{file_id}:0",
            file_id=file_id,
            start_s=0.0,
            end_s=20.0,
            trimmed_start_s=0.0,
            trimmed_end_s=20.0,
            best_center_s=10.0,
            score=0.5 + index / 100,
            outcome="selected" if selected else "candidate",
            order=index + 1 if selected else None,
            metrics=Metrics(
                sharpness=100.0 + index,
                exposure_clipped=0.0,
                motion=0.3,
                stability=0.9,
                colorfulness=0.2,
            ),
        )
    return manifest


@pytest.fixture
def state(qtbot: Any) -> ProjectState:
    """A state object. ``qtbot`` is here to guarantee a QApplication exists."""
    assert qtbot is not None
    return ProjectState()


def test_a_new_project_writes_nothing_until_it_is_saved(
    state: ProjectState, tmp_path: Path
) -> None:
    out = tmp_path / "edit"

    state.new_project([tmp_path], out)

    assert state.is_open
    assert state.manifest is not None
    assert state.manifest.sources == [tmp_path.resolve()]
    # The folder exists, because the user chose it, but nothing has been written yet.
    assert out.is_dir()
    assert not (out / "manifest.json").exists()


def test_a_new_project_over_an_existing_one_keeps_the_analysis(
    state: ProjectState, tmp_path: Path
) -> None:
    """The scenario from the spec: choosing a folder that holds a project continues it."""
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")

    state.new_project([tmp_path], out)

    assert state.manifest is not None
    assert len(state.manifest.segments) == 4


def test_opening_a_folder_without_a_manifest_says_so(state: ProjectState, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        state.open_project(tmp_path)


def test_opening_reads_the_config_beside_the_manifest(state: ProjectState, tmp_path: Path) -> None:
    """The CLI and the window share ``autocut.toml``, so opening has to read it."""
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    (out / "autocut.toml").write_text("[selection]\nmax_clips = 7\n", encoding="utf-8")

    state.open_project(out)

    assert state.config.selection.max_clips == 7


def test_a_mutation_is_saved_within_the_debounce(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    state.manifest.segments.clear() if state.manifest else None

    with qtbot.waitSignal(state.saved, timeout=AUTOSAVE_DEBOUNCE_MS + 3000):
        state.touch(["f0:0"])

    assert (out / "manifest.json").exists()


def test_the_debounce_collapses_a_burst_into_one_save(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    """Dragging a slider is one save, not one per pixel, which is the point of the timer."""
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    saves: list[int] = []
    state.saved.connect(lambda: saves.append(1))

    for _ in range(20):
        state.touch()

    with qtbot.waitSignal(state.saved, timeout=AUTOSAVE_DEBOUNCE_MS + 3000):
        pass
    qtbot.wait(200)

    assert saves == [1]


def test_save_now_writes_immediately_and_cancels_the_pending_save(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    """Closing the window must not wait for a timer that will never fire again."""
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    saves: list[int] = []
    state.saved.connect(lambda: saves.append(1))

    state.touch()
    state.save_now()
    qtbot.wait(AUTOSAVE_DEBOUNCE_MS + 300)

    assert saves == [1]
    written = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert written["schema_version"]


def test_closing_saves_and_forgets(state: ProjectState, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)

    state.close_project()

    assert not state.is_open
    assert (out / "manifest.json").exists()


def test_the_config_snapshot_follows_a_profile_change(state: ProjectState, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    state.config.selection.max_clips = 12

    state.refresh_config_snapshot()

    assert state.manifest is not None
    assert state.manifest.config_snapshot["selection"]["max_clips"] == 12


def test_a_stage_reports_progress_and_finishes(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    events: list[ProgressEvent] = []
    state.progress.connect(events.append)

    def work(progress: ProgressCallback) -> str:
        progress(ProgressEvent(stage="analyze", current=1, total=2))
        progress(ProgressEvent(stage="analyze", current=2, total=2))
        return "did it"

    with qtbot.waitSignal(state.stage_finished, timeout=5000) as blocker:
        assert state.run_stage("analysis", work)

    assert blocker.args == ["analysis"]
    assert [event.current for event in events] == [1, 2]
    assert state.last_result == "did it"
    # A finished stage saves without waiting for the debounce.
    assert (out / "manifest.json").exists()


def test_a_second_stage_is_refused_while_one_runs(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    """Two stages over one manifest would race, so the second is refused, not queued."""
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    gate = threading.Event()

    def slow(_progress: ProgressCallback) -> None:
        gate.wait(5.0)

    errors: list[str] = []
    state.error.connect(errors.append)
    assert state.run_stage("analysis", slow)

    refused = state.run_stage("selection", lambda _progress: None)
    gate.set()
    state.wait_for_stage(5000)
    qtbot.wait(50)

    assert refused is False
    assert errors == ["analysis is still running"]


def test_an_armed_autosave_does_not_fire_into_a_running_stage(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    """The save reads every segment; the worker is writing them. The two must not overlap.

    A review edit arms the debounce, then a stage starts before it fires. The timer has
    to be stopped, not left to go off mid run, and the one save has to be the stage's
    own at the end.
    """
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    saves: list[int] = []
    state.saved.connect(lambda: saves.append(1))
    gate = threading.Event()

    state.touch(["f0:0"])  # arms the debounce
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))

    # Well past the debounce, with the worker still holding the manifest.
    qtbot.wait(AUTOSAVE_DEBOUNCE_MS + 400)
    assert saves == []
    assert not (out / "manifest.json").exists()
    # A save asked for by hand is refused for the same reason.
    assert state.save_now() is False

    with qtbot.waitSignal(state.stage_finished, timeout=5000):
        gate.set()

    assert saves == [1]
    assert (out / "manifest.json").exists()


def test_nothing_new_is_scheduled_during_a_stage(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    saves: list[int] = []
    state.saved.connect(lambda: saves.append(1))
    gate = threading.Event()
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))

    state.touch(["f0:0"])
    qtbot.wait(AUTOSAVE_DEBOUNCE_MS + 400)

    assert saves == []
    gate.set()
    state.wait_for_stage(5000)
    qtbot.wait(100)


def test_closing_during_a_stage_cancels_waits_and_then_saves(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    """The one save allowed during a run, and only because it cancels and waits first."""
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    started = threading.Event()

    def work(progress: ProgressCallback) -> None:
        started.set()
        for index in range(200):
            progress(ProgressEvent(stage="analyze", current=index, total=200))
            time.sleep(0.01)

    assert state.run_stage("analysis", work)
    assert started.wait(5.0)

    state.close_project()

    assert not state.is_running
    assert (out / "manifest.json").exists()
    assert not state.is_open


def test_a_failing_stage_reports_and_logs_the_traceback(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)

    def work(_progress: ProgressCallback) -> None:
        raise RuntimeError("the card was pulled")

    with qtbot.waitSignal(state.error, timeout=5000) as blocker:
        state.run_stage("analysis", work)

    assert "the card was pulled" in blocker.args[0]
    log = (out / "gui-errors.log").read_text(encoding="utf-8")
    assert "RuntimeError" in log


def test_a_stale_cancel_does_not_kill_the_next_run(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    """Cancelling one run must not cancel the next one before it has begun."""
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    state.cancel()

    with qtbot.waitSignal(state.stage_finished, timeout=5000):
        state.run_stage("analysis", lambda progress: progress(ProgressEvent("analyze", 1, 1)))


def test_a_cancelled_stage_keeps_what_it_reached(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    out = tmp_path / "edit"
    state.new_project([tmp_path], out)
    state.manifest.files.update(a_manifest(out).files) if state.manifest else None

    gate = threading.Event()

    def work(progress: ProgressCallback) -> None:
        progress(ProgressEvent(stage="analyze", current=1, total=9))
        gate.wait(5.0)
        progress(ProgressEvent(stage="analyze", current=2, total=9))

    def press_cancel(_event: object) -> None:
        state.cancel()
        gate.set()

    state.progress.connect(press_cancel)
    with qtbot.waitSignal(state.stage_cancelled, timeout=5000) as blocker:
        state.run_stage("analysis", work)

    assert blocker.args == ["analysis"]
    # Cancelled, but the files the run had already probed are on disk.
    saved = Manifest.load(out / "manifest.json")
    assert len(saved.files) == 4


def test_selection_runs_on_the_ui_thread_and_emits_once(
    state: ProjectState, tmp_path: Path
) -> None:
    """The live slider depends on this: re-select, one signal, no worker."""
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    state.open_project(out)
    changes: list[int] = []
    state.selection_changed.connect(lambda: changes.append(1))

    assert state.run_selection()

    assert changes == [1]
    assert state.manifest is not None
    assert any(segment.outcome == "selected" for segment in state.manifest.segments.values())


def test_selection_is_refused_while_a_stage_runs(
    state: ProjectState, tmp_path: Path, qtbot: Any
) -> None:
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    state.open_project(out)
    gate = threading.Event()
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))

    refused = state.run_selection()
    gate.set()
    state.wait_for_stage(5000)
    qtbot.wait(50)

    assert refused is False

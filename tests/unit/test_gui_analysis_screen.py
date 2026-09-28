"""The Analysis screen: running the real pipeline on the synthetic clips, and stopping it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from autocut.core.events import ProgressEvent  # noqa: E402
from autocut.core.manifest import Manifest  # noqa: E402
from autocut.gui.screens.analysis import (  # noqa: E402
    AnalysisScreen,
    estimate_remaining,
    format_seconds,
)
from autocut.gui.state import AnalysisOutcome, ProjectState  # noqa: E402
from tests.unit.test_gui_state import a_manifest  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def state_and_screen(qtbot: Any, tmp_path: Path) -> tuple[ProjectState, AnalysisScreen]:
    state = ProjectState()
    screen = AnalysisScreen(state)
    qtbot.addWidget(screen)
    return state, screen


def test_the_screen_says_to_open_a_project_first(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
) -> None:
    _state, screen = state_and_screen

    assert not screen.run_button.isEnabled()
    assert "Open a project first" in screen.summary.text()


def test_the_button_offers_a_re_run_on_a_finished_project(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    state, screen = state_and_screen
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")

    state.open_project(out)

    assert screen.run_button.text() == "Re-run analysis"
    assert not screen.is_incomplete()
    assert "4 segments from 4 files" in screen.summary.text()


def test_the_button_offers_a_resume_when_a_file_was_never_reached(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    """A probed file with no segment and no error is a file a cancel left behind."""
    state, screen = state_and_screen
    out = tmp_path / "edit"
    out.mkdir()
    manifest = a_manifest(out)
    del manifest.segments["f3:0"]
    manifest.save(out / "manifest.json")

    state.open_project(out)

    assert screen.is_incomplete()
    assert screen.run_button.text() == "Resume analysis"


def test_an_unreadable_file_is_not_a_reason_to_resume(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    """A file ffprobe could not read will never produce a segment, however often it runs."""
    state, screen = state_and_screen
    out = tmp_path / "edit"
    out.mkdir()
    manifest = a_manifest(out)
    del manifest.segments["f3:0"]
    manifest.files["f3"].error = "moov atom not found"
    manifest.save(out / "manifest.json")

    state.open_project(out)

    assert not screen.is_incomplete()


def test_the_steps_and_the_bar_follow_the_progress_events(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    state, screen = state_and_screen
    state.new_project([tmp_path], tmp_path / "edit")

    screen._on_started("analysis")
    screen._on_progress(ProgressEvent(stage="probe", current=2, total=8, path=Path("GX01.MP4")))

    assert screen.bar.maximum() == 8
    assert screen.bar.value() == 2
    assert "GX01.MP4" in screen.current_file.text()
    assert "elapsed" in screen.timing.text()
    assert screen.steps.state("scan") == "done"
    assert screen.steps.state("probe") == "running"
    assert screen.steps.state("analyze") == "waiting"


def test_a_cached_file_is_labelled_as_one(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    _state, screen = state_and_screen

    screen._on_progress(
        ProgressEvent(
            stage="analyze", current=1, total=3, path=Path("a.MP4"), extra={"cached": True}
        )
    )

    assert "(cached)" in screen.current_file.text()


def test_a_stage_with_no_total_gets_an_indeterminate_bar(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
) -> None:
    _state, screen = state_and_screen

    screen._on_progress(ProgressEvent(stage="scan", current=0, total=0))

    assert screen.bar.maximum() == 0


def test_the_summary_uses_the_same_numbers_as_the_cli(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    from autocut.core.describe import DescribeResult
    from autocut.core.embeddings import EmbedResult
    from autocut.core.tags import TagResult

    state, screen = state_and_screen
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    state.open_project(out)
    outcome = AnalysisOutcome(
        files=6,
        unreadable=1,
        segments=17,
        cached_files=2,
        embed=EmbedResult(model="ViT-B-32", device="cpu", segments=17),
        tag=TagResult(embedded=17, with_a_tag=14),
        describe=DescribeResult(described=5, requests=5),
    )

    text = screen.describe_outcome(outcome)

    assert "17 segments from 6 files (2 from cache, 1 unreadable)" in text
    assert "Embedded 17 segments with ViT-B-32 on cpu" in text
    assert "Tagged 14 of 17 embedded segments" in text
    assert "Described 5 segments in 5 requests" in text


def test_the_summary_says_why_a_stage_was_skipped(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    from autocut.core.describe import DescribeResult
    from autocut.core.embeddings import EmbedResult

    state, screen = state_and_screen
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    state.open_project(out)
    outcome = AnalysisOutcome(
        files=1,
        segments=1,
        embed=EmbedResult(skipped_reason="the ai extra is not installed"),
        describe=DescribeResult(skipped_reason="no API key"),
    )

    text = screen.describe_outcome(outcome)

    assert "Embeddings skipped: the ai extra is not installed." in text
    assert "Descriptions skipped: no API key." in text


def test_clearing_the_cache_reports_what_it_removed(
    state_and_screen: tuple[ProjectState, AnalysisScreen], tmp_path: Path
) -> None:
    from autocut.core.cache import cache_dir

    state, screen = state_and_screen
    state.new_project([tmp_path], tmp_path / "edit")
    state.config.cache.dir = tmp_path / "cache"
    # Through cache_dir, because the cache keeps its entries under a schema folder and
    # a test that writes beside it would be clearing nothing.
    entry = cache_dir(state.config) / "abc.npz"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_bytes(b"stale")

    screen._clear_cache()

    assert "Removed 1 cache entries" in screen.summary.text()
    assert not entry.exists()


def test_seconds_are_formatted_for_a_person() -> None:
    assert format_seconds(9) == "0:09"
    assert format_seconds(75) == "1:15"
    assert format_seconds(3725) == "1:02:05"
    assert format_seconds(-4) == "0:00"


def test_no_estimate_is_offered_from_a_single_file() -> None:
    """One file pays for every warm up there is, so its rate is not the run's rate."""
    assert estimate_remaining(elapsed=10.0, current=1, total=40) is None
    assert estimate_remaining(elapsed=0.0, current=5, total=40) is None
    assert estimate_remaining(elapsed=10.0, current=5, total=40) == pytest.approx(70.0)


@pytest.mark.ffmpeg
def test_a_real_analysis_run_fills_the_project(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
    tmp_path: Path,
    synthetic_dir: Path,
    qtbot: Any,
) -> None:
    """The whole point: the window runs the same pipeline the CLI does."""
    state, screen = state_and_screen
    out = tmp_path / "edit"
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert screen.run()

    manifest = Manifest.load(out / "manifest.json")
    assert manifest.files
    assert manifest.segments
    assert screen.bar.value() == 100
    assert "segments from" in screen.summary.text()
    assert screen.run_button.text() == "Re-run analysis"


@pytest.mark.ffmpeg
def test_a_cancelled_run_keeps_what_it_analysed_and_can_be_resumed(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
    tmp_path: Path,
    synthetic_dir: Path,
    qtbot: Any,
) -> None:
    """Cancel mid run, then resume: the cache makes the second run cheap and complete."""
    state, screen = state_and_screen
    out = tmp_path / "edit"
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"
    state.config.analysis.workers = 1

    def cancel_after_the_third_file(event: object) -> None:
        if isinstance(event, ProgressEvent) and event.stage == "analyze" and event.current >= 3:
            state.cancel()

    state.progress.connect(cancel_after_the_third_file)
    with qtbot.waitSignal(state.stage_cancelled, timeout=180_000):
        assert screen.run()

    assert state.wait_for_stage(30_000)
    partial = Manifest.load(out / "manifest.json")
    assert partial.files
    assert "Cancelled" in screen.current_file.text()
    analysed_after_cancel = len({segment.file_id for segment in partial.segments.values()})
    assert analysed_after_cancel < len(partial.files)
    assert screen.is_incomplete()
    assert screen.run_button.text() == "Resume analysis"

    state.progress.disconnect(cancel_after_the_third_file)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert screen.run()

    finished = Manifest.load(out / "manifest.json")
    readable = [source for source in finished.files.values() if source.error is None]
    assert len({segment.file_id for segment in finished.segments.values()}) >= len(readable) - 1
    assert not screen.is_incomplete()


# --- the stage cards --------------------------------------------------------


def test_a_screen_without_a_project_offers_to_open_one(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
) -> None:
    _state, screen = state_and_screen
    asked: list[int] = []
    screen.open_project_requested.connect(lambda: asked.append(1))

    assert screen.stack.currentWidget() is screen.empty
    screen.open_project_button.click()

    assert asked == [1]


def test_every_stage_has_a_card_and_starts_waiting(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
) -> None:
    from autocut.gui.screens.analysis import STAGE_TITLES

    _state, screen = state_and_screen

    assert list(screen.steps.cards) == [key for key, _ in STAGE_TITLES]
    assert all(card.state == "waiting" for card in screen.steps.cards.values())
    assert all(
        card.title == title
        for (_, title), card in zip(STAGE_TITLES, screen.steps.cards.values(), strict=True)
    )


def test_a_running_stage_carries_a_mono_counter(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
) -> None:
    from autocut.core.events import ProgressEvent

    _state, screen = state_and_screen

    screen._on_progress(ProgressEvent(stage="probe", current=12, total=72, message="", path=None))

    assert screen.steps.cards["probe"].counter.text() == "12 / 72"
    assert screen.steps.state("probe") == "running"


def test_finishing_ticks_every_stage_and_drops_the_counters(
    state_and_screen: tuple[ProjectState, AnalysisScreen],
) -> None:
    from autocut.core.events import ProgressEvent

    _state, screen = state_and_screen

    screen._on_progress(ProgressEvent(stage="probe", current=12, total=72, message="", path=None))
    screen._on_finished("analysis")

    assert all(card.state == "done" for card in screen.steps.cards.values())
    assert screen.steps.cards["probe"].counter.text() == ""

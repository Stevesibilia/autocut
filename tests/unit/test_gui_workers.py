"""The worker thread: progress out, cancellation in, and never taking the window down."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

pytest.importorskip("PySide6")

from autocut.core.events import ProgressCallback, ProgressEvent  # noqa: E402
from autocut.gui.workers import CancelFlag, CoreWorker  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def workers() -> Iterator[list[CoreWorker]]:
    """Every worker a test starts, waited for before the test ends.

    ``done``, ``cancelled`` and ``failed`` are emitted from inside ``run``, so the
    thread is still winding down when the test's assertions pass. A ``QThread`` object
    collected while its thread is still running makes Qt abort the process, which is a
    flake that looks like a crash rather than like a test bug.
    """
    started: list[CoreWorker] = []
    yield started
    for worker in started:
        assert worker.wait(10_000), f"{worker.name} never finished"


def counting_work(total: int = 5) -> Callable[[ProgressCallback], int]:
    """A stage that reports ``total`` units and returns how many it finished."""

    def work(progress: ProgressCallback) -> int:
        done = 0
        for index in range(1, total + 1):
            progress(ProgressEvent(stage="analyze", current=index, total=total))
            done = index
        return done

    return work


def test_progress_events_and_the_result_come_back(qtbot: Any, workers: list[CoreWorker]) -> None:
    seen: list[ProgressEvent] = []
    worker = CoreWorker("analysis", counting_work(4), CancelFlag())
    workers.append(worker)
    worker.progressed.connect(seen.append)

    with qtbot.waitSignal(worker.done, timeout=5000) as blocker:
        worker.start()

    assert blocker.args == [4]
    assert [event.current for event in seen] == [1, 2, 3, 4]


def test_progress_is_delivered_on_the_thread_that_owns_the_widgets(
    qtbot: Any, workers: list[CoreWorker]
) -> None:
    """Qt widgets may only be touched from the main thread, so the slot has to run there.

    The connection is automatic, which means Qt queues the emission across the thread
    boundary. This asserts the queueing actually happened rather than trusting it.
    """
    main_thread = threading.get_ident()
    slot_threads: list[int] = []
    worker_threads: list[int] = []

    def work(progress: ProgressCallback) -> None:
        worker_threads.append(threading.get_ident())
        progress(ProgressEvent(stage="analyze", current=1, total=1))

    worker = CoreWorker("analysis", work, CancelFlag())
    workers.append(worker)
    worker.progressed.connect(lambda _event: slot_threads.append(threading.get_ident()))

    with qtbot.waitSignal(worker.done, timeout=5000):
        worker.start()
    qtbot.wait(50)

    assert worker_threads and worker_threads[0] != main_thread
    assert slot_threads == [main_thread]


class GatedWork:
    """A stage the test steps through one unit at a time.

    The cancellation contract is about ordering, so a test of it has to control the
    ordering rather than hope for it. Before each unit the worker announces that it has
    arrived and parks; the test decides when to release it, and can set the cancel flag
    while the worker is parked, which is the only moment at which "the flag was set
    before this unit" is a fact rather than a race.

    The first version raced: the flag was set from a queued slot after unit three's
    report, and on a slow machine it landed before that same report's own flag check,
    so the run stopped at three instead of four. The GitHub runner found it, twice.
    """

    def __init__(self, units: int = 10) -> None:
        self.units = units
        self.arrived = [threading.Event() for _ in range(units + 1)]
        self.released = [threading.Event() for _ in range(units + 1)]
        self.reached: list[int] = []
        self.reported: list[int] = []

    def __call__(self, progress: ProgressCallback) -> int:
        for index in range(1, self.units + 1):
            self.arrived[index].set()
            assert self.released[index].wait(10.0), f"unit {index} was never released"
            self.reached.append(index)
            progress(ProgressEvent(stage="analyze", current=index, total=self.units))
            self.reported.append(index)
        return len(self.reached)

    def step(self, index: int) -> None:
        """Let one unit run and wait until the next one has parked."""
        assert self.arrived[index].wait(10.0), f"unit {index} never started"
        self.released[index].set()
        if index < self.units:
            assert self.arrived[index + 1].wait(10.0), f"unit {index + 1} never started"

    def park_at(self, index: int) -> None:
        """Wait until the worker is parked before ``index``, having reported ``index - 1``."""
        for unit in range(1, index):
            self.step(unit)
        assert self.arrived[index].wait(10.0), f"unit {index} never started"

    def release(self, index: int) -> None:
        self.released[index].set()


def test_a_cancel_stops_between_units(qtbot: Any, workers: list[CoreWorker]) -> None:
    """The flag is read by the progress callback, which is where the core offers to stop.

    The unit in flight is finished first, which is what the core does too: it reports a
    file after analysing it, so a cancel seen at file four's report stops the run there
    with four's work done and three's already saved.
    """
    flag = CancelFlag()
    work = GatedWork()
    worker = CoreWorker("analysis", work, flag)
    workers.append(worker)

    with qtbot.waitSignal(worker.cancelled, timeout=10_000):
        worker.start()
        # Three units run and report; the worker is then parked before the fourth.
        work.park_at(4)
        assert work.reported == [1, 2, 3]
        # Set while the worker is parked, so "the flag was set before unit four" is a
        # fact and not a hope.
        flag.cancel()
        work.release(4)

    assert work.reached == [1, 2, 3, 4]
    assert work.reported == [1, 2, 3]


def test_the_flag_is_read_between_units_and_not_during_one(
    qtbot: Any, workers: list[CoreWorker]
) -> None:
    """Cancelling while a unit is in flight lets that unit finish, and no more."""
    flag = CancelFlag()
    work = GatedWork()
    worker = CoreWorker("analysis", work, flag)
    workers.append(worker)

    with qtbot.waitSignal(worker.cancelled, timeout=10_000):
        worker.start()
        work.park_at(1)
        flag.cancel()
        work.release(1)

    # The first unit's own work was done before its report raised.
    assert work.reached == [1]
    assert work.reported == []


def test_a_cancelled_stage_does_not_report_done(qtbot: Any, workers: list[CoreWorker]) -> None:
    flag = CancelFlag()
    flag.cancel()
    worker = CoreWorker("analysis", counting_work(3), flag)
    workers.append(worker)
    finished: list[object] = []
    worker.done.connect(finished.append)

    with qtbot.waitSignal(worker.cancelled, timeout=5000):
        worker.start()
    qtbot.wait(50)

    assert finished == []


def test_an_exception_becomes_a_message_and_a_traceback(
    qtbot: Any, workers: list[CoreWorker]
) -> None:
    def work(_progress: ProgressCallback) -> None:
        raise RuntimeError("ffprobe went missing")

    worker = CoreWorker("analysis", work, CancelFlag())
    workers.append(worker)

    with qtbot.waitSignal(worker.failed, timeout=5000) as blocker:
        worker.start()

    assert blocker.args == ["analysis failed: ffprobe went missing"]
    assert "RuntimeError" in worker.traceback_text
    assert "ffprobe went missing" in worker.traceback_text


def test_a_stage_that_returns_nothing_still_reports_done(
    qtbot: Any, workers: list[CoreWorker]
) -> None:
    worker = CoreWorker("analysis", lambda _progress: None, CancelFlag())
    workers.append(worker)

    with qtbot.waitSignal(worker.done, timeout=5000) as blocker:
        worker.start()

    assert blocker.args == [None]


def test_the_flag_is_set_and_cleared() -> None:
    flag = CancelFlag()

    assert not flag.cancelled
    flag.cancel()
    assert flag.cancelled
    flag.clear()
    assert not flag.cancelled

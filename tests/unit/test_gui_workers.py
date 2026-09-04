"""The worker thread: progress out, cancellation in, and never taking the window down."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("PySide6")

from autocut.core.events import ProgressCallback, ProgressEvent  # noqa: E402
from autocut.gui.workers import CancelFlag, CoreWorker  # noqa: E402

pytestmark = pytest.mark.gui


def counting_work(total: int = 5) -> Callable[[ProgressCallback], int]:
    """A stage that reports ``total`` units and returns how many it finished."""

    def work(progress: ProgressCallback) -> int:
        done = 0
        for index in range(1, total + 1):
            progress(ProgressEvent(stage="analyze", current=index, total=total))
            done = index
        return done

    return work


def test_progress_events_and_the_result_come_back(qtbot: Any) -> None:
    seen: list[ProgressEvent] = []
    worker = CoreWorker("analysis", counting_work(4), CancelFlag())
    worker.progressed.connect(seen.append)

    with qtbot.waitSignal(worker.done, timeout=5000) as blocker:
        worker.start()

    assert blocker.args == [4]
    assert [event.current for event in seen] == [1, 2, 3, 4]


def test_progress_is_delivered_on_the_thread_that_owns_the_widgets(qtbot: Any) -> None:
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
    worker.progressed.connect(lambda _event: slot_threads.append(threading.get_ident()))

    with qtbot.waitSignal(worker.done, timeout=5000):
        worker.start()
    qtbot.wait(50)

    assert worker_threads and worker_threads[0] != main_thread
    assert slot_threads == [main_thread]


def test_a_cancel_stops_between_units(qtbot: Any) -> None:
    """The flag is read by the progress callback, which is where the core offers to stop.

    The unit in flight is finished first, which is what the core does too: it reports a
    file after analysing it, so a cancel granted at file three's report stops the run at
    file four's, with four's work already done and three's already saved. The gate makes
    that deterministic instead of a race with the event loop, since the real cancel comes
    from a button press on the main thread.
    """
    flag = CancelFlag()
    reached: list[int] = []
    gate = threading.Event()

    def work(progress: ProgressCallback) -> None:
        for index in range(1, 11):
            reached.append(index)
            progress(ProgressEvent(stage="analyze", current=index, total=10))
            if index == 3:
                gate.wait(5.0)

    def press_cancel(event: ProgressEvent) -> None:
        if event.current == 3:
            flag.cancel()
            gate.set()

    worker = CoreWorker("analysis", work, flag)
    worker.progressed.connect(press_cancel)

    with qtbot.waitSignal(worker.cancelled, timeout=5000):
        worker.start()

    assert reached == [1, 2, 3, 4]


def test_a_cancelled_stage_does_not_report_done(qtbot: Any) -> None:
    flag = CancelFlag()
    flag.cancel()
    worker = CoreWorker("analysis", counting_work(3), flag)
    finished: list[object] = []
    worker.done.connect(finished.append)

    with qtbot.waitSignal(worker.cancelled, timeout=5000):
        worker.start()
    qtbot.wait(50)

    assert finished == []


def test_an_exception_becomes_a_message_and_a_traceback(qtbot: Any) -> None:
    def work(_progress: ProgressCallback) -> None:
        raise RuntimeError("ffprobe went missing")

    worker = CoreWorker("analysis", work, CancelFlag())

    with qtbot.waitSignal(worker.failed, timeout=5000) as blocker:
        worker.start()

    assert blocker.args == ["analysis failed: ffprobe went missing"]
    assert "RuntimeError" in worker.traceback_text
    assert "ffprobe went missing" in worker.traceback_text


def test_a_stage_that_returns_nothing_still_reports_done(qtbot: Any) -> None:
    worker = CoreWorker("analysis", lambda _progress: None, CancelFlag())

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

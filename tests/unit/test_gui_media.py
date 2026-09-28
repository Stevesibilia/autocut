"""Queued stops for the media players, and the nested loop that lets them run."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from autocut.gui.widgets.media import NativeStop  # noqa: E402

pytestmark = pytest.mark.gui


def test_settle_runs_the_queued_stop(qtbot: Any) -> None:
    """Anything with a `stop` slot will do in place of a player."""
    del qtbot
    timer = QTimer()
    timer.start(60_000)
    stopper = NativeStop()

    stopper.request(timer)

    assert timer.isActive()
    assert stopper.pending
    stopper.settle()
    assert not timer.isActive()
    assert not stopper.pending


def test_settle_leaves_user_input_for_the_outer_loop(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A click waiting in the queue must not re-enter a widget while it settles a stop.

    Checked through the flag rather than with a posted click: Qt holds back input
    still in the window system queue, which is where a real click waits, but an event
    handed to `postEvent` is an ordinary posted event and is delivered either way, so a
    synthetic click cannot tell the two loops apart.
    """
    del qtbot
    flags: list[object] = []
    original = QEventLoop.exec

    def spy(loop: QEventLoop, *args: object) -> int:
        flags.extend(args)
        return int(original(loop, *args))  # type: ignore[arg-type]

    monkeypatch.setattr(QEventLoop, "exec", spy)
    timer = QTimer()
    timer.start(60_000)
    stopper = NativeStop()
    stopper.request(timer)

    stopper.settle()

    assert not timer.isActive()
    assert flags == [QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents]

"""Stopping a `QMediaPlayer` without holding the GIL.

`QMediaPlayer.stop()` called from Python keeps the GIL for the whole native call. The
FFmpeg backend tears its audio renderer down on another thread, and that renderer's
`~QObject` holds Qt's signal-slot mutex while it asks Shiboken for the GIL to look up a
Python override of `disconnectNotify`. The UI thread, still inside `stop()`, then waits
for that same mutex, and the window freezes for good. It was found under Docker, where
it hung the test suite one run in three, and nothing about it is specific to Docker.

So the widgets never call the native stop directly. `NativeStop.request` queues the C++
slot, which the event loop then runs with the GIL released, and `settle` lets a queued
stop run before the same player is started again. See design decision 7 of
`gui-worker-offload`.
"""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt, Slot


def spin_event_loop() -> None:
    """Run the events already posted to this thread, with the GIL released.

    `QEventLoop.exec` is one of the calls PySide releases the GIL for, and the quit is
    queued behind whatever was posted before it, so everything already waiting runs
    first and nothing posted afterwards does. User input is left for the outer loop:
    this runs inside widget methods such as Play, and a click delivered here would
    re-enter the widget before the method that called it has returned.
    """
    loop = QEventLoop()
    QMetaObject.invokeMethod(loop, "quit", Qt.ConnectionType.QueuedConnection)
    loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)


class NativeStop(QObject):
    """One widget's queued stops, and whether one is still waiting to run."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending = False

    @property
    def pending(self) -> bool:
        return self._pending

    def request(self, player: QObject) -> None:
        """Stop `player` from the event loop. It is still playing when this returns."""
        QMetaObject.invokeMethod(player, "stop", Qt.ConnectionType.QueuedConnection)
        # Queued behind the stop, so it runs after it: posted events to one thread are
        # delivered in the order they were posted.
        QMetaObject.invokeMethod(self, "_ran", Qt.ConnectionType.QueuedConnection)
        self._pending = True

    def settle(self) -> None:
        """Let a queued stop run now, before the player is given anything new.

        Without this, Stop and then Play in the same turn of the event loop would have
        the stop land on the new playback.
        """
        if self._pending:
            spin_event_loop()

    @Slot()
    def _ran(self) -> None:
        self._pending = False

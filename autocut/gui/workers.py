"""Running a core stage off the UI thread.

The core's long operations take a ``ProgressCallback`` and cancel by having that
callback raise, which is exactly the shape a Qt worker needs: one thread, one
callable, progress out through a signal, cancellation in through a flag the callback
reads. Nothing here knows what stage it is running, so a stage added to the core
needs no change on this side as long as it keeps reporting progress the same way.

Only the manifest crosses the thread boundary, and only one way. While a stage runs
the manifest belongs to the worker: the core mutates it in place and the UI reads
nothing from it but the progress events, because every control that could touch it is
disabled for the duration. When the worker finishes, ownership returns to the UI
thread, which is where the result is applied and the file is written. See ADR 9.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from autocut.core.analyze import AnalysisCancelled
from autocut.core.events import ProgressCallback, ProgressEvent


class CancelFlag:
    """A cancel request the worker thread and the UI thread can both see.

    A ``threading.Event`` rather than a bool, because the UI thread sets it while the
    worker thread reads it and only one of those two is guaranteed to be atomic by
    accident. Nothing waits on it: it is polled by the progress callback, which is the
    only place the core offers to stop.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class CoreWorker(QThread):
    """One core stage on one thread.

    ``work`` is called with a progress callback and returns whatever the stage
    returns, which travels back through ``done`` untouched. A stage that raises
    reports through ``failed`` with the message and logs the traceback, because a
    dialog is not the place for a stack trace but a bug report is.
    """

    progressed = Signal(object)
    """A ``ProgressEvent`` from the stage, emitted on the worker thread."""

    done = Signal(object)
    """Whatever the stage returned. ``None`` for a stage that returns nothing."""

    failed = Signal(str)
    """A one line message. The traceback goes to ``traceback_text``."""

    cancelled = Signal()
    """The stage stopped because the flag was set, which is not a failure."""

    def __init__(
        self,
        name: str,
        work: Callable[[ProgressCallback], Any],
        flag: CancelFlag,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self._work = work
        self._flag = flag
        self.traceback_text: str = ""

    def run(self) -> None:  # pragma: no cover - exercised through start() in tests
        try:
            result = self._work(self._callback)
        except AnalysisCancelled:
            self.cancelled.emit()
        except Exception as error:  # noqa: BLE001 - a stage must never take the window down
            self.traceback_text = traceback.format_exc()
            self.failed.emit(f"{self.name} failed: {error}")
        else:
            self.done.emit(result)

    def _callback(self, event: ProgressEvent) -> None:
        """The core's progress callback: report, then stop if asked.

        Reporting first means the event that was already computed is not thrown away by
        a cancel arriving in the same instant, so the progress bar and the file name
        agree with what the stage actually finished.
        """
        self.progressed.emit(event)
        if self._flag.cancelled:
            raise AnalysisCancelled(f"{self.name} cancelled")

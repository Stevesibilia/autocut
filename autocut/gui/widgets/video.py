"""The one check between a caller and `QMediaPlayer.setVideoOutput`.

`clicked` carries the button's checked state, so `button.clicked.connect(self.play)` on
a `play(video_output=None)` hands `False` straight through to Qt, which raises deep
inside `setVideoOutput` with a message about argument types and nothing about the
button that caused it. That is the regression this module exists to make impossible:
the value is checked where it is understood, and the error names the caller.

Buttons should still be connected through a zero argument slot. This is the guard for
the day somebody forgets, and it fires in the test suite rather than on a user's
machine.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject


def checked_video_output(value: Any, caller: str) -> QObject | None:
    """`value` if it is something Qt can render into, otherwise a `TypeError`.

    `None` means "the widget's own video output" and is the normal case. Anything else
    has to be a `QObject`, which covers both a `QVideoWidget` and the `QVideoSink` a
    test counts frames in.
    """
    if value is None or isinstance(value, QObject):
        return value
    raise TypeError(
        f"{caller} got {value!r} as its video output. "
        "A video output is None or a QObject; a bool here means a clicked(bool) signal "
        "was connected straight to it, so connect through a zero argument slot instead."
    )

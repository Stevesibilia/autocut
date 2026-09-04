"""The PySide6 desktop application.

A consumer of ``autocut.core``, never a second implementation of it: every stage the
window runs is the same function the CLI calls. Nothing in ``autocut.core`` imports
from here. See ADR 9 for the state and worker shape, and SPEC.md section 11 for the
screens.

Importing this package imports PySide6, so the CLI does it inside the ``gui`` command
and reports the missing extra rather than failing at start up.
"""

from __future__ import annotations

from os import PathLike
from pathlib import Path

__all__ = ["run"]


def run(project: str | PathLike[str] | None = None) -> int:
    """Start the window. Imported lazily so ``import autocut.gui`` stays cheap."""
    from autocut.gui.app import run as _run

    return _run(Path(project) if project is not None else None)

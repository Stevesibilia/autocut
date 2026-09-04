"""Progress and event reporting for the core library.

The core never prints. Long operations accept a ``ProgressCallback`` and call it
with ``ProgressEvent`` instances. The CLI renders them with Rich, the GUI with
Qt signals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Stage = Literal[
    "scan",
    "probe",
    "analyze",
    "embed",
    "tag",
    "describe",
    "geocode",
    "select",
    "soundtrack",
    "sync",
    "export",
]


@dataclass(slots=True)
class ProgressEvent:
    """One unit of progress within a stage."""

    stage: Stage
    current: int
    total: int
    path: Path | None = None
    message: str = ""
    extra: dict[str, object] = field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]


def null_progress(_: ProgressEvent) -> None:
    """Default callback that discards events."""

"""One runner for every external tool AutoCut shells out to.

Ten hand-written ``subprocess.run`` sites used to differ in how they handled a
missing binary, a non-zero exit and a timeout, not because the differences meant
anything but because each was written on its own. ``run_tool`` is the one place
that decides what those three failures look like; everything else stays
site-specific argument building and result parsing.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


class ToolMissingError(RuntimeError):
    """A required external binary is not on PATH."""


def require_tools(*names: str) -> None:
    """Raise :class:`ToolMissingError` once, naming every missing binary at once."""
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise ToolMissingError(f"{', '.join(missing)} not found on PATH. Run `autocut doctor`.")


@dataclass(frozen=True, slots=True)
class ToolRun:
    """What running one external tool produced. Never raised, always returned."""

    returncode: int
    stdout: str
    stderr: str
    error: str | None = None
    """Set when the tool could not be run at all: missing from PATH, or timed out."""

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0


def run_tool(command: list[str], *, timeout_s: float) -> ToolRun:
    """Run ``command`` and capture the result. Never raises for the tool's own failure."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return ToolRun(
            returncode=127, stdout="", stderr="", error=f"{command[0]} not found on PATH"
        )
    except subprocess.TimeoutExpired:
        return ToolRun(
            returncode=1,
            stdout="",
            stderr="",
            error=f"{command[0]} timed out after {timeout_s:g}s",
        )
    except OSError as exc:
        return ToolRun(returncode=1, stdout="", stderr="", error=str(exc))
    return ToolRun(
        returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
    )


def first_stderr_line(text: str) -> str:
    """The first non-blank line, which is where ffmpeg and ffprobe put the reason."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""

"""The ``autocut gui`` command: the lazy import, and what it says without the extra.

No Qt here on purpose. The point of the command is that it can be typed on a machine
without PySide6 and get a sentence instead of a traceback, and that is exactly what a
test without the extra installed can check.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autocut.cli.main import app

runner = CliRunner()


def test_a_missing_gui_extra_is_one_clear_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """``None`` in ``sys.modules`` is how the import machinery reports a blocked module."""
    monkeypatch.setitem(sys.modules, "autocut.gui.app", None)

    result = runner.invoke(app, ["gui"])

    assert result.exit_code == 1
    assert "gui extra is not installed" in result.stdout
    assert 'pip install -e ".[gui]"' in result.stdout


def test_the_command_hands_the_project_folder_to_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Path | None] = []
    fake = types.ModuleType("autocut.gui.app")
    # `**_` so a parameter added to `run` later changes the command's tests, not these
    # stand-ins: what this asserts is that the project folder arrives.
    fake.run = lambda project=None, **_: seen.append(project) or 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "autocut.gui.app", fake)

    result = runner.invoke(app, ["gui", str(tmp_path)])

    assert result.exit_code == 0
    assert seen == [tmp_path]


def test_the_window_exit_code_is_the_command_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """A window that fails has to fail the command, or a script cannot tell."""
    fake = types.ModuleType("autocut.gui.app")
    fake.run = lambda project=None, **_: 3  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "autocut.gui.app", fake)

    result = runner.invoke(app, ["gui"])

    assert result.exit_code == 3


def test_gui_is_in_the_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert "gui" in result.stdout


def test_diagnose_is_offered_without_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag has to reach the lazy import like everything else in this command."""
    monkeypatch.setitem(sys.modules, "autocut.gui.app", None)

    result = runner.invoke(app, ["gui", "--diagnose"])

    assert result.exit_code == 1
    assert "gui extra is not installed" in result.stdout


def test_diagnose_calls_the_report_and_never_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It exists so a Mac report can carry numbers, so it must not open a window."""
    called: list[str] = []
    fake = types.ModuleType("autocut.gui.app")
    fake.run = lambda project=None, **_: called.append("run") or 0  # type: ignore[attr-defined]
    fake.diagnose = lambda: called.append("diagnose") or 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "autocut.gui.app", fake)

    result = runner.invoke(app, ["gui", "--diagnose"])

    assert result.exit_code == 0
    assert called == ["diagnose"]


def test_the_window_is_asked_to_log_when_verbose(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []
    fake = types.ModuleType("autocut.gui.app")
    fake.run = lambda project=None, verbose=False: seen.append(verbose) or 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "autocut.gui.app", fake)

    assert runner.invoke(app, ["gui", "--verbose"]).exit_code == 0
    assert runner.invoke(app, ["gui"]).exit_code == 0

    assert seen == [True, False]

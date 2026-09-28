"""The one runner every external tool site goes through."""

from __future__ import annotations

import sys

import pytest

from autocut.core.proc import (
    ToolMissingError,
    first_stderr_line,
    require_tools,
    run_tool,
)


def test_a_successful_run_has_no_error() -> None:
    result = run_tool([sys.executable, "-c", "print('hi')"], timeout_s=10.0)
    assert result.ok
    assert result.error is None
    assert result.returncode == 0
    assert result.stdout.strip() == "hi"


def test_a_non_zero_exit_is_not_an_error_but_is_not_ok() -> None:
    result = run_tool([sys.executable, "-c", "import sys; sys.exit(3)"], timeout_s=10.0)
    assert result.error is None
    assert not result.ok
    assert result.returncode == 3


def test_a_missing_binary_is_reported_as_such() -> None:
    result = run_tool(["autocut-tool-that-does-not-exist"], timeout_s=10.0)
    assert result.error == "autocut-tool-that-does-not-exist not found on PATH"
    assert result.returncode == 127
    assert not result.ok


def test_a_timeout_is_reported_as_such() -> None:
    command = [sys.executable, "-c", "import time; time.sleep(5)"]
    result = run_tool(command, timeout_s=0.2)
    assert result.error == f"{sys.executable} timed out after 0.2s"
    assert not result.ok


def test_first_stderr_line_skips_leading_blank_lines() -> None:
    assert first_stderr_line("\n\n  \nreal message\nmore\n") == "real message"


def test_first_stderr_line_of_blank_text_is_blank() -> None:
    assert first_stderr_line("\n  \n") == ""


def test_require_tools_passes_when_everything_is_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    require_tools("ffmpeg", "ffprobe")


def test_require_tools_names_every_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None if name == "ffprobe" else "/usr/bin/x")
    with pytest.raises(ToolMissingError) as excinfo:
        require_tools("ffmpeg", "ffprobe")
    assert "ffprobe" in str(excinfo.value)
    assert "ffmpeg" not in str(excinfo.value)
    assert "autocut doctor" in str(excinfo.value)

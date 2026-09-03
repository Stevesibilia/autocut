"""Shared fixtures. See ADR 8 for the synthetic versus private fixture split."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"
PRIVATE = FIXTURES / "private"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_private = pytest.mark.skip(reason="no clips in tests/fixtures/private")
    skip_real = pytest.mark.skip(reason="AUTOCUT_REAL_FOOTAGE not set")
    skip_ffmpeg = pytest.mark.skip(reason="ffmpeg not on PATH")
    has_private = PRIVATE.exists() and any(
        p.suffix.lower() in {".mp4", ".mov"} for p in PRIVATE.iterdir()
    )
    has_real = bool(os.environ.get("AUTOCUT_REAL_FOOTAGE"))
    has_ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    for item in items:
        if "private" in item.keywords and not has_private:
            item.add_marker(skip_private)
        if "real_footage" in item.keywords and not has_real:
            item.add_marker(skip_real)
        if "ffmpeg" in item.keywords and not has_ffmpeg:
            item.add_marker(skip_ffmpeg)


@pytest.fixture(autouse=True)
def plain_cli_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Rich render CLI output as plain, unwrapped text.

    Rich styles and wraps to the terminal it detects. On a CI runner that means
    ANSI escapes inside option names and a panel wrapped at 80 columns, so a
    substring assertion on ``--no-proxies`` fails for reasons that have nothing
    to do with the command. Pinning the environment keeps the assertions about
    behavior.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    # The CLI builds its console at import time, so it captured the environment as it
    # was before this fixture ran. Replace it with one built under the pinned settings.
    from rich.console import Console

    from autocut.cli import main

    monkeypatch.setattr(main, "console", Console())


@pytest.fixture(scope="session")
def synthetic_dir() -> Path:
    if not SYNTHETIC.exists():
        pytest.skip("run scripts/make_fixtures.py first")
    return SYNTHETIC


@pytest.fixture(scope="session")
def private_dir() -> Path:
    return PRIVATE


@pytest.fixture(scope="session")
def real_footage_dir() -> Path:
    return Path(os.environ["AUTOCUT_REAL_FOOTAGE"])

"""Shared fixtures. See ADR 8 for the synthetic versus private fixture split."""

from __future__ import annotations

import importlib.util
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"
PRIVATE = FIXTURES / "private"


def pytest_configure(config: pytest.Config) -> None:
    """Never open a real window from the test suite.

    The ``gui`` tests build widgets, and on a developer machine with a display Qt
    would happily map them, stealing focus for the length of the run. Offscreen is
    what the Docker target and CI use, so the venv uses it too unless the platform
    was chosen deliberately.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_private = pytest.mark.skip(reason="no clips in tests/fixtures/private")
    skip_real = pytest.mark.skip(reason="AUTOCUT_REAL_FOOTAGE not set")
    skip_ffmpeg = pytest.mark.skip(reason="ffmpeg not on PATH")
    skip_ai = pytest.mark.skip(reason="the ai extra is not installed")
    skip_gui = pytest.mark.skip(reason="the gui extra is not installed")
    has_private = PRIVATE.exists() and any(
        p.suffix.lower() in {".mp4", ".mov"} for p in PRIVATE.iterdir()
    )
    has_real = bool(os.environ.get("AUTOCUT_REAL_FOOTAGE"))
    has_ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    # find_spec rather than an import: importing torch costs seconds and this runs
    # during collection, on every test session, extra installed or not.
    has_ai = importlib.util.find_spec("torch") is not None
    has_gui = importlib.util.find_spec("PySide6") is not None
    for item in items:
        if "private" in item.keywords and not has_private:
            item.add_marker(skip_private)
        if "real_footage" in item.keywords and not has_real:
            item.add_marker(skip_real)
        if "ffmpeg" in item.keywords and not has_ffmpeg:
            item.add_marker(skip_ffmpeg)
        if "ai" in item.keywords and not has_ai:
            item.add_marker(skip_ai)
        if "gui" in item.keywords and not has_gui:
            item.add_marker(skip_gui)


@pytest.fixture(autouse=True)
def no_model_downloads(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test that is not marked ``ai`` away from the real vision model.

    ``autocut analyze`` embeds and tags at the end when the ai extra is installed, and
    a CLI test points the cache at its own ``tmp_path``. On a machine with the extra
    that meant every such test downloading 600 MB of weights into a fresh directory:
    the unit suite took fifteen minutes and left 18 GB in ``/tmp``. Tests that want the
    seams patch the probe themselves, which overrides this.
    """
    if "ai" in request.keywords:
        return
    from autocut.core import embeddings

    monkeypatch.setattr(embeddings, "_probe", (False, "the ai extra is switched off for this test"))


@pytest.fixture(autouse=True)
def config_files_in_tmp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Never let a test read or write the developer's own configuration files.

    The recent projects list and the window layout live in the platform config
    directory, so a GUI test that opens a project would otherwise add it to the real
    list, a screenshot of the Project screen would show whatever folders this machine
    happens to have opened, and a test that drags a splitter would rearrange the
    developer's own window. Patched for every test rather than in the GUI ones, because
    these files are outside the repository and nothing in a test run has any business
    touching them.
    """
    if importlib.util.find_spec("PySide6") is None:
        yield
        return
    from autocut.gui import layout, recent

    directory = tmp_path_factory.mktemp("config")
    originals = (recent.recent_path, layout.layout_path)
    recent.recent_path = lambda: directory / "recent.json"  # type: ignore[assignment]
    layout.layout_path = lambda path=None: path or directory / "layout.json"  # type: ignore[assignment]
    try:
        yield
    finally:
        recent.recent_path, layout.layout_path = originals  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def stop_media_players() -> Iterator[None]:
    """Stop every player before the widgets holding it are collected.

    A ``QMediaPlayer`` whose widget is garbage collected while it is still playing
    takes the process down: the Qt ffmpeg backend keeps a thread on the file, and in
    the container, where the audio backend is a stub, it segfaults on the way out.
    The suite reports every test as passed and then dies, which is the same shape of
    problem as the GUI worker threads had.
    """
    yield
    if importlib.util.find_spec("PySide6") is None:
        return
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance()
    if application is None:
        return
    from autocut.gui.widgets.media import spin_event_loop
    from autocut.gui.widgets.montage import MontagePlayer
    from autocut.gui.widgets.preview import PreviewPanel

    for widget in application.allWidgets():
        if isinstance(widget, PreviewPanel | MontagePlayer):
            widget.stop()
    # The stops are queued (widgets.media), so they have not happened yet. One turn of
    # the loop runs them, with the GIL released, before the widgets are collected.
    spin_event_loop()


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

    from autocut.cli import output

    monkeypatch.setattr(output, "console", Console())


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

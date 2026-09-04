"""One PNG per screen, on the synthetic project, for a reviewer to look at.

Offscreen tests prove a window builds and behaves. They prove nothing about whether
it is readable, and nobody can review a layout from an assertion. So this walks the
five screens on a real analysed project and grabs each one.

The images go to ``$AUTOCUT_GUI_SHOTS`` and nowhere else: never into the repository,
and only ever of the synthetic fixtures, because ADR 8 keeps private footage out of
git and a screenshot of a holiday is private footage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from autocut.gui.app import SCREENS, build_window  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.ffmpeg]


def shots_dir() -> Path | None:
    """Where to write, or ``None`` when the reviewer did not ask for images."""
    raw = os.environ.get("AUTOCUT_GUI_SHOTS", "").strip()
    return Path(raw) if raw else None


def test_every_screen_can_be_grabbed_on_the_synthetic_project(
    tmp_path: Path, synthetic_dir: Path, qtbot: Any
) -> None:
    """Walk the screens on an analysed project, and save a PNG each when asked to.

    The grab itself runs whether or not a directory was given, because a screen that
    cannot be rendered is a bug worth failing on in CI, where nobody collects images.
    """
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"

    window = build_window(state)
    qtbot.addWidget(window)
    window.resize(1280, 800)

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        analysis = window.screens["analysis"]
        assert analysis.run()  # type: ignore[attr-defined]
    assert state.run_selection()
    window.refresh_navigation()

    directory = shots_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in SCREENS:
        window.go_to(spec.key)
        qtbot.wait(50)
        image = window.grab().toImage()
        assert not image.isNull(), spec.key
        assert image.width() > 0 and image.height() > 0
        if directory is not None:
            path = directory / f"{spec.key}.png"
            assert image.save(str(path)), path
            written.append(path)

    if directory is not None:
        assert [path.name for path in written] == [f"{spec.key}.png" for spec in SCREENS]
        assert all(path.stat().st_size > 0 for path in written)


def test_the_screens_are_grabbed_before_a_project_exists(tmp_path: Path, qtbot: Any) -> None:
    """The empty window is what a first time user sees, so it is worth an image too."""
    window = build_window()
    qtbot.addWidget(window)
    window.resize(1280, 800)

    image = window.grab().toImage()

    assert not image.isNull()
    directory = shots_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "empty.png"
        assert image.save(str(path))
        assert path.stat().st_size > 0

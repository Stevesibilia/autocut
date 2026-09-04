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
from autocut.gui.screens.review import ReviewScreen  # noqa: E402
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


def test_every_review_state_is_grabbed(tmp_path: Path, synthetic_dir: Path, qtbot: Any) -> None:
    """The Review screen in each of the states a reviewer puts it in.

    One image per state, because the states are what a layout review is about: a grid
    of cards, a clip in the preview with its bounds, a filtered grid, the groups mode,
    and a clip kept and another rejected by hand.
    """
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"
    # Sprites so the cards can scrub, which is what the GUI's own analysis run does.
    state.config.analysis.sprites = True

    window = build_window(state)
    qtbot.addWidget(window)
    window.resize(1400, 880)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert window.screens["analysis"].run()  # type: ignore[attr-defined]
    assert state.run_selection()
    window.refresh_navigation()
    window.go_to("review")
    review = window.screens["review"]
    assert isinstance(review, ReviewScreen)
    qtbot.wait(100)

    directory = shots_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)

    def grab(name: str) -> None:
        qtbot.wait(60)
        image = window.grab().toImage()
        assert not image.isNull(), name
        if directory is not None:
            path = directory / f"review-{name}.png"
            assert image.save(str(path)), path
            assert path.stat().st_size > 0

    grab("grid")

    first = review.grid.visible_ids()[0]
    review.grid.select_segment(first)
    review.grid.hover(first, 0.6)
    grab("hover-and-preview")

    review.sort_box.setCurrentIndex(1)
    review.class_box.setCurrentIndex(1)
    grab("filtered")
    review.class_box.setCurrentIndex(0)
    review.sort_box.setCurrentIndex(0)

    ids = review.grid.visible_ids()
    review.grid.select_segment(ids[0])
    review._decide("keep")
    if len(ids) > 1:
        review.grid.select_segment(ids[1])
        review._decide("reject")
    grab("decisions")

    review.groups_toggle.setChecked(True)
    grab("groups")
    review.groups_toggle.setChecked(False)


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

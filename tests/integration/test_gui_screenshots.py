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

from PySide6.QtWidgets import QApplication  # noqa: E402

from autocut.gui.app import SCREENS, apply_theme, build_window  # noqa: E402
from autocut.gui.screens.export import ExportScreen  # noqa: E402
from autocut.gui.screens.review import ReviewScreen  # noqa: E402
from autocut.gui.screens.soundtrack import SoundtrackScreen  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.ffmpeg]

#: Both token sets, because the light one is a design nobody has looked at until it is
#: rendered and half a design system is the one that is never checked.
THEMES = ("dark", "light")


def shots_dir() -> Path | None:
    """Where to write, or ``None`` when the reviewer did not ask for images."""
    raw = os.environ.get("AUTOCUT_GUI_SHOTS", "").strip()
    return Path(raw) if raw else None


def test_every_screen_can_be_grabbed_in_both_themes(
    tmp_path: Path, synthetic_dir: Path, qtbot: Any
) -> None:
    """Walk the screens on an analysed project, in each theme, saving a PNG each.

    The grab itself runs whether or not a directory was given, because a screen that
    cannot be rendered is a bug worth failing on in CI, where nobody collects images.

    A fresh window per theme rather than restyling the one that is already up: the rail
    builds its icons in the colours of the theme that was active when it was made, and
    a light window wearing the dark rail's icons would be a screenshot of a bug that
    does not exist.
    """
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"

    first = build_window(state)
    qtbot.addWidget(first)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert first.screens["analysis"].run()  # type: ignore[attr-defined]
    assert state.wait_for_stage(30_000)
    assert state.run_selection()

    directory = shots_dir()
    written: list[Path] = []
    for name in THEMES:
        state.config.gui.theme = name
        window = build_window(state)
        qtbot.addWidget(window)
        window.resize(1280, 800)
        window.refresh_navigation()

        into = directory / name if directory is not None else None
        if into is not None:
            into.mkdir(parents=True, exist_ok=True)
        for spec in SCREENS:
            window.go_to(spec.key)
            qtbot.wait(50)
            image = window.grab().toImage()
            assert not image.isNull(), f"{name}/{spec.key}"
            assert image.width() > 0 and image.height() > 0
            if into is not None:
                path = into / f"{spec.key}.png"
                assert image.save(str(path)), path
                written.append(path)
        # Not closed: closing a window closes the project it is showing, and the next
        # theme would have been grabbed on an empty one.
        window.hide()

    if directory is not None:
        assert [path.name for path in written] == [
            f"{spec.key}.png" for _ in THEMES for spec in SCREENS
        ]
        assert all(path.stat().st_size > 0 for path in written)
    # Back to the default, so the tests that follow are grabbed in the approved set.
    apply_theme(QApplication.instance(), "dark")


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
    assert state.wait_for_stage(30_000)
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


def test_the_soundtrack_and_export_states_are_grabbed(
    tmp_path: Path, synthetic_dir: Path, qtbot: Any
) -> None:
    """The last two screens in the states the music loop and the export put them in.

    The click fixture stands in for a Suno track, which is the only reproducible way to
    have a real tempo on a synthetic project.
    """
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"

    window = build_window(state)
    qtbot.addWidget(window)
    window.resize(1400, 880)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert window.screens["analysis"].run()  # type: ignore[attr-defined]
    assert state.wait_for_stage(30_000)
    assert state.run_selection()
    window.refresh_navigation()

    directory = shots_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)

    def grab(name: str) -> None:
        qtbot.wait(60)
        image = window.grab().toImage()
        assert not image.isNull(), name
        if directory is not None:
            path = directory / f"{name}.png"
            assert image.save(str(path)), path
            assert path.stat().st_size > 0

    # --- the soundtrack screen -------------------------------------------
    window.go_to("soundtrack")
    soundtrack = window.screens["soundtrack"]
    assert isinstance(soundtrack, SoundtrackScreen)
    grab("soundtrack-empty")

    assert soundtrack.generate()
    grab("soundtrack-prompt")

    lines = soundtrack.editor.structure_lines()
    lines[1] = "[slow, dark intro]"
    soundtrack.editor.structure.setPlainText("\n".join(lines))
    soundtrack.editor.revalidate()
    grab("soundtrack-invalid-edit")
    soundtrack.editor.show_variant(soundtrack._state.manifest.soundtrack.variants[0])

    with qtbot.waitSignal(soundtrack.track_loaded, timeout=60_000):
        assert soundtrack.load_track(synthetic_dir / "click_120bpm.wav")
    assert state.wait_for_stage(30_000)
    grab("soundtrack-track")

    with qtbot.waitSignal(state.stage_finished, timeout=60_000):
        assert soundtrack.apply_sync()
    assert state.wait_for_stage(30_000)
    grab("soundtrack-synced")

    # --- the export screen ------------------------------------------------
    window.go_to("export")
    export = window.screens["export"]
    assert isinstance(export, ExportScreen)
    export.reload()
    grab("export-options")

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert export.run()
    grab("export-done")

    assert export.summary.text()


def test_the_montage_states_are_grabbed(tmp_path: Path, synthetic_dir: Path, qtbot: Any) -> None:
    """The montage player, empty and playing, on the Review and Soundtrack screens."""
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"
    state.config.analysis.sprites = True

    window = build_window(state)
    qtbot.addWidget(window)
    window.resize(1400, 880)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert window.screens["analysis"].run()  # type: ignore[attr-defined]
    assert state.wait_for_stage(30_000)
    assert state.run_selection()
    window.refresh_navigation()

    directory = shots_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)

    def grab(name: str) -> None:
        qtbot.wait(80)
        image = window.grab().toImage()
        assert not image.isNull(), name
        if directory is not None:
            path = directory / f"{name}.png"
            assert image.save(str(path)), path

    window.go_to("review")
    review = window.screens["review"]
    assert isinstance(review, ReviewScreen)
    grab("montage-before")

    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert review.play_all()
    assert state.wait_for_stage(30_000)
    qtbot.wait(400)
    grab("montage-playing")
    review.montage.pause()

    # The same player on the Soundtrack screen, with the track muxed.
    window.go_to("soundtrack")
    soundtrack = window.screens["soundtrack"]
    assert isinstance(soundtrack, SoundtrackScreen)
    assert soundtrack.generate()
    with qtbot.waitSignal(soundtrack.track_loaded, timeout=60_000):
        assert soundtrack.load_track(synthetic_dir / "click_120bpm.wav")
    assert state.wait_for_stage(30_000)
    with qtbot.waitSignal(state.stage_finished, timeout=60_000):
        assert soundtrack.apply_sync()
    assert state.wait_for_stage(30_000)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert soundtrack.play_with_track()
    assert state.wait_for_stage(30_000)
    qtbot.wait(400)
    grab("montage-with-track")
    soundtrack.montage.pause()


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


def test_the_review_screen_is_grabbed_at_both_window_sizes(
    tmp_path: Path, synthetic_dir: Path, qtbot: Any
) -> None:
    """The design size and the smallest the window may be dragged to.

    The regression these prove against was a window that could not be made smaller at
    all, so a picture of the small one is the point of the change.
    """
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"
    state.config.analysis.sprites = True

    window = build_window(state)
    qtbot.addWidget(window)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert window.screens["analysis"].run()  # type: ignore[attr-defined]
    assert state.wait_for_stage(30_000)
    assert state.run_selection()
    window.refresh_navigation()
    window.go_to("review")

    directory = shots_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)

    gui = state.config.gui
    for width, height in ((1440, 900), (gui.min_window_width, gui.min_window_height)):
        window.resize(width, height)
        qtbot.wait(80)

        assert (window.width(), window.height()) == (width, height)
        image = window.grab().toImage()
        assert not image.isNull()
        if directory is not None:
            path = directory / f"review-{width}x{height}.png"
            assert image.save(str(path)), path
            assert path.stat().st_size > 0


def test_the_workspace_arrangements_are_grabbed(
    tmp_path: Path, synthetic_dir: Path, qtbot: Any
) -> None:
    """The three arrangements the splitter and the rail make possible."""
    out = tmp_path / "edit"
    state = ProjectState()
    state.new_project([synthetic_dir], out)
    state.config.cache.dir = tmp_path / "cache"
    state.config.analysis.sprites = True

    window = build_window(state)
    qtbot.addWidget(window)
    window.resize(1440, 900)
    with qtbot.waitSignal(state.stage_finished, timeout=180_000):
        assert window.screens["analysis"].run()  # type: ignore[attr-defined]
    assert state.wait_for_stage(30_000)
    assert state.run_selection()
    window.refresh_navigation()
    window.go_to("review")
    window.show()
    qtbot.waitExposed(window)
    review = window.screens["review"]
    assert isinstance(review, ReviewScreen)
    review.set_panel_visible(True)
    review.apply_default_split()
    qtbot.wait(60)

    directory = shots_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)

    def grab(name: str) -> None:
        qtbot.wait(80)
        image = window.grab().toImage()
        assert not image.isNull(), name
        if directory is not None:
            path = directory / f"{name}.png"
            assert image.save(str(path)), path
            assert path.stat().st_size > 0

    grab("workspace-default")

    window.rail.set_collapsed(True)
    grab("workspace-rail-collapsed")
    window.rail.set_collapsed(False)

    review.set_split([max(review.splitter.width() - 600, 0), 600])
    qtbot.wait(60)
    review.preview.show_segment(review.grid.visible_ids()[0])
    review.preview.play()
    qtbot.wait(400)
    grab("workspace-wide-panel-playing")
    review.preview.stop()

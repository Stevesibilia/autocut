"""The window: which screens a project has earned, and what closing it does."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402

from autocut.gui.app import SCREENS, MainWindow, build_window, screen_available  # noqa: E402
from autocut.gui.screens.placeholder import PlaceholderScreen  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from tests.unit.test_gui_state import a_manifest  # noqa: E402

pytestmark = pytest.mark.gui

SPECS = {spec.key: spec for spec in SCREENS}


@pytest.fixture
def window(qtbot: Any) -> MainWindow:
    win = build_window()
    qtbot.addWidget(win)
    return win


def enabled(win: MainWindow, key: str) -> bool:
    row = next(index for index, spec in enumerate(SCREENS) if spec.key == key)
    return bool(win.nav.item(row).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_the_five_screens_are_listed_in_order(window: MainWindow) -> None:
    labels = [window.nav.item(row).text() for row in range(window.nav.count())]

    assert labels == ["Project", "Analysis", "Review", "Soundtrack", "Export"]


def test_without_a_project_only_the_project_screen_is_reachable(window: MainWindow) -> None:
    assert enabled(window, "project")
    assert not enabled(window, "analysis")
    assert not enabled(window, "review")
    assert not enabled(window, "export")


def test_an_open_project_unlocks_analysis_but_not_review(
    window: MainWindow, tmp_path: Path
) -> None:
    window.state.new_project([tmp_path], tmp_path / "edit")
    window.refresh_navigation()

    assert enabled(window, "analysis")
    assert not enabled(window, "review")


def test_segments_unlock_review_and_a_selection_unlocks_export(
    window: MainWindow, tmp_path: Path
) -> None:
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    window.state.open_project(out)

    assert enabled(window, "review")
    assert not enabled(window, "soundtrack")
    assert not enabled(window, "export")

    assert window.state.run_selection()

    assert enabled(window, "soundtrack")
    assert enabled(window, "export")


def test_the_enabling_rules_need_no_window(tmp_path: Path) -> None:
    """The reason they are a function: a rule is testable without building widgets."""
    manifest = a_manifest(tmp_path)

    assert screen_available(SPECS["project"], None)
    assert not screen_available(SPECS["analysis"], None)
    assert screen_available(SPECS["review"], manifest)
    assert not screen_available(SPECS["export"], manifest)

    manifest.segments["f0:0"].outcome = "selected"
    assert screen_available(SPECS["export"], manifest)


def test_a_project_with_files_but_no_segments_cannot_be_reviewed(tmp_path: Path) -> None:
    manifest = a_manifest(tmp_path)
    manifest.segments.clear()

    assert screen_available(SPECS["analysis"], manifest)
    assert not screen_available(SPECS["review"], manifest)


def test_the_navigation_switches_the_visible_screen(window: MainWindow) -> None:
    window.go_to("review")

    assert window.stack.currentWidget() is window.screens["review"]


def test_the_three_later_screens_name_the_change_that_fills_them(window: MainWindow) -> None:
    for key, change in (
        ("review", "m5-gui-review"),
        ("soundtrack", "m5-gui-soundtrack-export"),
        ("export", "m5-gui-soundtrack-export"),
    ):
        screen = window.screens[key]
        assert isinstance(screen, PlaceholderScreen)
        labels = [child.text() for child in screen.findChildren(type(screen.children()[1]))]
        assert any(change in text for text in labels), key


def test_the_title_names_the_open_project(window: MainWindow, tmp_path: Path) -> None:
    out = tmp_path / "sardinia"

    window.state.new_project([tmp_path], out)
    window.refresh_navigation()

    assert "sardinia" in window.windowTitle()


def test_opening_a_project_moves_to_the_analysis_screen(
    window: MainWindow, tmp_path: Path, qtbot: Any
) -> None:
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    project = window.screens["project"]

    assert project.open_project(out)  # type: ignore[attr-defined]

    assert window.stack.currentWidget() is window.screens["analysis"]


def test_an_error_from_the_state_reaches_the_status_bar(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dialog is suppressed, because a modal box in a test is a hang."""
    from autocut.gui import app as app_module

    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda *args, **kwargs: None)

    window.state.error.emit("ffmpeg is not on PATH")

    assert (
        "ffmpeg is not on PATH" in window.statusBar().findChildren(type(window._status))[0].text()
    )


def test_closing_saves_the_project(window: MainWindow, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    window.state.new_project([tmp_path], out)

    window.closeEvent(QCloseEvent())

    assert (out / "manifest.json").exists()
    assert not window.state.is_open


def test_closing_cancels_a_running_stage(window: MainWindow, tmp_path: Path, qtbot: Any) -> None:
    """A thread left running behind a closed window is a hang on quit."""
    import threading

    out = tmp_path / "edit"
    window.state.new_project([tmp_path], out)
    gate = threading.Event()
    state: ProjectState = window.state
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))

    gate.set()
    window.closeEvent(QCloseEvent())

    assert not state.is_running

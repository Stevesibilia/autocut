"""The Project screen: dropping folders, the profile diff, creating and reopening."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402

from autocut.gui.screens.project import ProjectScreen, count_videos  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from tests.unit.test_gui_state import a_manifest  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def recent_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Never touch the developer's own recent list from a test."""
    store = tmp_path / "recent.json"
    from autocut.gui import recent as recent_module

    monkeypatch.setattr(recent_module, "recent_path", lambda: store)
    from autocut.gui.screens import project as project_module

    monkeypatch.setattr(project_module, "load_recent", recent_module.load_recent)
    return store


@pytest.fixture
def screen(qtbot: Any) -> ProjectScreen:
    widget = ProjectScreen(ProjectState())
    qtbot.addWidget(widget)
    return widget


def a_card_folder(root: Path, clips: int = 3) -> Path:
    """A folder that looks like a memory card: video files with accepted extensions."""
    folder = root / "DCIM"
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(clips):
        (folder / f"GX01{index}.MP4").write_bytes(b"not really a video")
    (folder / "GX010.LRV").write_bytes(b"a proxy, which is not counted")
    (folder / "notes.txt").write_text("nor is this", encoding="utf-8")
    return folder


def drop(widget: Any, paths: list[Path]) -> None:
    """Synthesize a drop of local paths onto ``widget``."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    event = QDropEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)


def test_only_video_files_are_counted(tmp_path: Path) -> None:
    folder = a_card_folder(tmp_path, clips=4)

    assert count_videos(folder) == 4
    assert count_videos(tmp_path / "nowhere") == 0


def test_dropping_a_folder_adds_it_with_its_count(screen: ProjectScreen, tmp_path: Path) -> None:
    folder = a_card_folder(tmp_path, clips=3)

    drop(screen.sources, [folder])

    assert screen.sources.folders == [folder.resolve()]
    assert "3 clips" in screen.sources.item(0).text()
    assert "3 clips across 1 folder" in screen.count_label.text()


def test_dropping_a_file_adds_the_folder_holding_it(screen: ProjectScreen, tmp_path: Path) -> None:
    """People drag a clip to show you where the footage is, and that is enough."""
    folder = a_card_folder(tmp_path, clips=2)

    drop(screen.sources, [folder / "GX010.MP4"])

    assert screen.sources.folders == [folder.resolve()]


def test_the_same_folder_is_not_added_twice(screen: ProjectScreen, tmp_path: Path) -> None:
    folder = a_card_folder(tmp_path)

    drop(screen.sources, [folder])
    drop(screen.sources, [folder])

    assert screen.sources.folders == [folder.resolve()]


def test_removing_a_folder_takes_the_right_row(screen: ProjectScreen, tmp_path: Path) -> None:
    first = a_card_folder(tmp_path / "a")
    second = a_card_folder(tmp_path / "b")
    drop(screen.sources, [first, second])

    screen.sources.setCurrentRow(0)
    screen.sources.remove_selected()

    assert screen.sources.folders == [second.resolve()]


def test_create_is_disabled_until_there_are_sources_and_an_output(
    screen: ProjectScreen, tmp_path: Path
) -> None:
    assert not screen.create_button.isEnabled()

    drop(screen.sources, [a_card_folder(tmp_path)])
    assert not screen.create_button.isEnabled()

    screen.output.setText(str(tmp_path / "edit"))
    assert screen.create_button.isEnabled()


def test_an_output_folder_that_already_holds_a_project_says_so(
    screen: ProjectScreen, tmp_path: Path
) -> None:
    """The scenario from the spec: the button offers to continue, not to start again."""
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")

    screen.output.setText(str(out))

    assert "already in this folder" in screen.output_note.text()
    assert screen.create_button.text() == "Continue project"


def test_the_family_profile_shows_its_diff_before_it_is_applied(screen: ProjectScreen) -> None:
    screen.profile.setCurrentIndex(
        next(
            index
            for index in range(screen.profile.count())
            if screen.profile.itemData(index) == "family"
        )
    )

    note = screen.profile_note.text()
    assert "It will change:" in note
    assert "selection.max_clips: 40 to 60" in note
    # Nothing is applied by looking at it.
    assert screen._state.config.selection.max_clips == 40


def test_creating_a_project_applies_the_profile_and_remembers_it(
    screen: ProjectScreen, tmp_path: Path, recent_in_tmp: Path
) -> None:
    out = tmp_path / "edit"
    drop(screen.sources, [a_card_folder(tmp_path)])
    screen.output.setText(str(out))
    screen.profile.setCurrentIndex(
        next(
            index
            for index in range(screen.profile.count())
            if screen.profile.itemData(index) == "drone"
        )
    )
    opened: list[int] = []
    screen.project_opened.connect(lambda: opened.append(1))

    assert screen.create_project()

    state = screen._state
    assert state.is_open
    assert state.config.weights.motion == pytest.approx(1.4)
    assert state.manifest is not None
    assert state.manifest.config_snapshot["weights"]["motion"] == pytest.approx(1.4)
    assert opened == [1]
    assert str(out.resolve()) in recent_in_tmp.read_text(encoding="utf-8")
    assert screen.recent.count() == 1


def test_reopening_a_project_puts_its_sources_back(screen: ProjectScreen, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    out.mkdir()
    folder = a_card_folder(tmp_path)
    manifest = a_manifest(out)
    manifest.sources = [folder]
    manifest.save(out / "manifest.json")

    assert screen.open_project(out)

    assert screen.sources.folders == [folder.resolve()]
    assert screen.output.text() == str(out)


def test_opening_a_folder_without_a_manifest_warns_and_changes_nothing(
    screen: ProjectScreen, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autocut.gui.screens import project as project_module

    warned: list[str] = []
    monkeypatch.setattr(
        project_module.QMessageBox,
        "warning",
        lambda _parent, _title, message: warned.append(message),
    )

    assert screen.open_project(tmp_path) is False

    assert warned and "manifest.json" in warned[0]
    assert not screen._state.is_open


def test_the_screen_shows_a_project_opened_from_somewhere_else(
    screen: ProjectScreen, tmp_path: Path
) -> None:
    """``autocut gui <folder>`` opens the project on the state, not through this screen."""
    out = tmp_path / "edit"
    out.mkdir()
    folder = a_card_folder(tmp_path)
    manifest = a_manifest(out)
    manifest.sources = [folder]
    manifest.save(out / "manifest.json")

    screen._state.open_project(out)

    assert screen.sources.folders == [folder.resolve()]
    assert screen.output.text() == str(out)


def test_the_doctor_report_is_on_the_screen(screen: ProjectScreen) -> None:
    """A missing ffmpeg has to be visible before a run, not discovered during one."""
    text = screen.doctor.text()

    assert "ffmpeg" in text
    assert "ffprobe" in text


def test_the_settings_button_asks_the_window(screen: ProjectScreen) -> None:
    asked: list[int] = []
    screen.settings_requested.connect(lambda: asked.append(1))

    screen.settings_requested.emit()

    assert asked == [1]

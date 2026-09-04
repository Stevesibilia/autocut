"""The recent projects list. No Qt, so it runs in the default suite."""

from __future__ import annotations

import json
from pathlib import Path

from autocut.gui.recent import MAX_RECENT, load_recent, recent_path, remember


def test_nothing_stored_is_an_empty_list(tmp_path: Path) -> None:
    assert load_recent(tmp_path / "recent.json") == []


def test_a_remembered_project_comes_back(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    project = tmp_path / "edit"
    project.mkdir()

    remember(project, store)

    assert load_recent(store) == [project.resolve()]


def test_the_newest_is_first_and_listed_once(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()

    remember(first, store)
    remember(second, store)
    remember(first, store)

    assert load_recent(store) == [first.resolve(), second.resolve()]


def test_the_list_stops_growing(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    for index in range(MAX_RECENT + 4):
        folder = tmp_path / f"p{index}"
        folder.mkdir()
        remember(folder, store)

    assert len(load_recent(store)) == MAX_RECENT


def test_a_project_that_has_been_deleted_is_dropped(tmp_path: Path) -> None:
    """The list must never offer to open a folder that is not there any more."""
    store = tmp_path / "recent.json"
    gone = tmp_path / "gone"
    gone.mkdir()
    kept = tmp_path / "kept"
    kept.mkdir()
    remember(gone, store)
    remember(kept, store)
    gone.rmdir()

    assert load_recent(store) == [kept.resolve()]


def test_a_corrupt_file_costs_the_convenience_and_nothing_else(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    store.write_text("{not json", encoding="utf-8")

    assert load_recent(store) == []


def test_a_file_that_is_not_a_list_is_ignored(tmp_path: Path) -> None:
    store = tmp_path / "recent.json"
    store.write_text(json.dumps({"projects": ["/tmp"]}), encoding="utf-8")

    assert load_recent(store) == []


def test_the_default_location_is_in_the_platform_config_dir() -> None:
    """Where it lives is a habit of this user, not a property of any one project."""
    path = recent_path()

    assert path.name == "recent.json"
    assert "autocut" in str(path).lower()

"""The per machine layout file.

A split position and a collapsed rail belong to this machine and this display, not to
the edit, so they live beside `recent.json` and never in the manifest. Nothing here is
worth an error: a bad file means the defaults, because a window that opens the way it
always did beats a window that will not open.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from autocut.gui.layout import LayoutState, load_layout, save_layout


def test_the_defaults_are_what_an_unarranged_window_wants() -> None:
    state = LayoutState()
    assert state.rail_collapsed is False
    assert state.review_split == []
    assert state.review_panel_visible is None


def test_a_layout_round_trips(tmp_path: Path) -> None:
    store = tmp_path / "layout.json"
    saved = LayoutState(rail_collapsed=True, review_split=[900, 540], review_panel_visible=False)

    assert save_layout(saved, store)

    assert load_layout(store) == saved


def test_a_missing_file_is_the_defaults(tmp_path: Path) -> None:
    assert load_layout(tmp_path / "nothing.json") == LayoutState()


def test_garbage_in_the_file_is_the_defaults_and_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = tmp_path / "layout.json"
    store.write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        state = load_layout(store)

    assert state == LayoutState()
    assert caplog.records


def test_a_file_that_is_not_an_object_is_the_defaults(tmp_path: Path) -> None:
    store = tmp_path / "layout.json"
    store.write_text('["not", "a", "layout"]', encoding="utf-8")

    assert load_layout(store) == LayoutState()


def test_a_key_from_a_newer_version_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    """Losing the whole layout over one unknown key would be worse than ignoring it."""
    store = tmp_path / "layout.json"
    store.write_text(
        json.dumps({"rail_collapsed": True, "something_new": {"nested": 1}}), encoding="utf-8"
    )

    state = load_layout(store)

    assert state.rail_collapsed is True
    assert state.review_split == []


@pytest.mark.parametrize(
    "raw",
    [
        {"rail_collapsed": "yes"},
        {"review_panel_visible": 3},
        {"review_split": "900,540"},
        {"review_split": [900, "540"]},
    ],
)
def test_a_value_of_the_wrong_shape_is_dropped(tmp_path: Path, raw: dict[str, object]) -> None:
    store = tmp_path / "layout.json"
    store.write_text(json.dumps(raw), encoding="utf-8")

    assert load_layout(store) == LayoutState()


def test_saving_into_a_directory_that_does_not_exist_yet_works(tmp_path: Path) -> None:
    store = tmp_path / "deeper" / "still" / "layout.json"

    assert save_layout(LayoutState(rail_collapsed=True), store)

    assert load_layout(store).rail_collapsed is True


def test_a_save_that_cannot_land_is_reported_not_raised(tmp_path: Path) -> None:
    """A read only config directory is a lost convenience, not a crash."""
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")

    assert save_layout(LayoutState(), blocked / "layout.json") is False


def test_the_default_path_sits_in_the_config_directory(tmp_path: Path) -> None:
    """Beside the recent projects list, and nowhere near a manifest.

    `layout_path` itself is redirected by the suite's own fixture, so this asks the
    module what it would compute rather than what the fixture returns.
    """
    del tmp_path
    from autocut.gui.layout import LAYOUT_NAME
    from autocut.gui.recent import RECENT_NAME, config_dir

    assert (config_dir() / LAYOUT_NAME).parent == (config_dir() / RECENT_NAME).parent
    assert LAYOUT_NAME == "layout.json"

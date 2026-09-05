"""The card delegate, where the model's roles become what a card shows.

`test_gui_card.py` already pins what a badge says. What is checked here is the wiring
either side of it: that the model answers the questions a card asks, that the delegate
reads them into the right marker, and that a card really is painted rather than silently
skipped, which is the failure a passing test suite would otherwise hide.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem  # noqa: E402

from autocut.core.manifest import PlaceInfo  # noqa: E402
from autocut.gui.models import SegmentRole, clock_label, lost_to_order, place_name  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from autocut.gui.theme import tokens  # noqa: E402
from autocut.gui.widgets.card import ACCENT, AMBER, MUTED  # noqa: E402
from autocut.gui.widgets.thumb_grid import ThumbGrid, placeholder_role  # noqa: E402
from tests.unit.test_gui_state import a_manifest  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def grid(qtbot: Any, tmp_path: Path) -> ThumbGrid:
    """A grid over a small project with places, timestamps, beats and a hero."""
    out = tmp_path / "edit"
    out.mkdir()
    manifest = a_manifest(out, clips=4, selected=True)
    manifest.places["0"] = PlaceInfo(place_id=0, name="Tancau sul Mare", segments=2)
    shot_at = datetime(2026, 7, 14, 12, 25, tzinfo=UTC)
    for index, (file_id, source) in enumerate(manifest.files.items()):
        source.creation_time = shot_at + timedelta(hours=index)
        source.source_class = ["drone", "actioncam", "phone", "reflex"][index]
        segment = manifest.segments[f"{file_id}:0"]
        segment.place_id = 0
        segment.beats = 8
    first = manifest.segments["f0:0"]
    first.duration_reason = "hero"
    loser = manifest.segments["f3:0"]
    loser.outcome = "candidate"
    loser.order = None
    loser.lost_to = "f1:0"
    loser.similarity_to_selected = 0.8123
    manifest.save(out / "manifest.json")

    state = ProjectState()
    state.open_project(out)
    widget = ThumbGrid(state)
    qtbot.addWidget(widget)
    return widget


def index_of(grid: ThumbGrid, segment_id: str) -> Any:
    for row in range(grid.proxy.rowCount()):
        index = grid.proxy.index(row, 0)
        if index.data(SegmentRole.SEGMENT_ID) == segment_id:
            return index
    raise AssertionError(f"{segment_id} is not in the grid")


# --- what the model answers -------------------------------------------------


def test_the_model_names_the_place(grid: ThumbGrid) -> None:
    assert index_of(grid, "f0:0").data(SegmentRole.PLACE_NAME) == "Tancau sul Mare"


def test_an_unnamed_place_falls_back_to_its_number(grid: ThumbGrid) -> None:
    manifest = grid._state.manifest
    assert manifest is not None
    manifest.places["1"] = PlaceInfo(place_id=1, segments=1)
    assert place_name(manifest, 1) == "place 1"
    assert place_name(manifest, None) == ""
    assert place_name(None, 0) == ""


def test_the_clock_is_the_file_time_plus_the_offset_into_it(grid: ThumbGrid) -> None:
    """A clip six minutes into a file was not shot when the file was opened."""
    manifest = grid._state.manifest
    assert manifest is not None
    source = manifest.files["f0"]
    assert clock_label(source, 0.0) == "12:25"
    assert clock_label(source, 360.0) == "12:31"
    source.creation_time = None
    assert clock_label(source, 0.0) == ""
    assert clock_label(None, 0.0) == ""


def test_the_model_counts_beats_and_marks_the_hero(grid: ThumbGrid) -> None:
    hero = index_of(grid, "f0:0")
    assert hero.data(SegmentRole.BEATS) == 8
    assert hero.data(SegmentRole.HERO) is True
    assert index_of(grid, "f1:0").data(SegmentRole.HERO) is False


def test_the_model_finds_the_edit_position_of_the_winner(grid: ThumbGrid) -> None:
    manifest = grid._state.manifest
    assert manifest is not None
    loser = index_of(grid, "f3:0")
    assert loser.data(SegmentRole.LOST_TO_ORDER) == manifest.segments["f1:0"].order
    assert lost_to_order(manifest, None) is None
    assert lost_to_order(manifest, "not a segment") is None


# --- what the delegate makes of it ------------------------------------------


def test_the_delegate_reads_a_selected_card_off_the_model(grid: ThumbGrid) -> None:
    marker = grid.delegate.marker(index_of(grid, "f1:0"))
    assert marker.badge == "IN 2"
    assert marker.tone == ACCENT
    assert marker.detail == "Tancau sul Mare · 13:25"


def test_the_delegate_names_what_a_candidate_lost_to(grid: ThumbGrid) -> None:
    marker = grid.delegate.marker(index_of(grid, "f3:0"))
    assert marker.badge == "OUT"
    assert marker.tone == MUTED
    assert marker.dimmed
    assert marker.detail == "lost to IN 2 · similar 0.81"


def test_the_delegate_follows_a_decision(grid: ThumbGrid) -> None:
    manifest = grid._state.manifest
    assert manifest is not None
    manifest.segments["f2:0"].user_decision = "keep"
    marker = grid.delegate.marker(index_of(grid, "f2:0"))
    assert marker.tone == AMBER
    assert marker.badge.startswith("KEPT")


def test_the_length_badge_shows_beats_only_once_the_edit_is_synced(grid: ThumbGrid) -> None:
    index = index_of(grid, "f0:0")
    assert grid.delegate._length_text(index) == "20.0 s · 8♪"
    manifest = grid._state.manifest
    assert manifest is not None
    manifest.segments["f0:0"].beats = None
    assert grid.delegate._length_text(index_of(grid, "f0:0")) == "20.0 s"


def test_each_source_class_has_its_own_placeholder() -> None:
    roles = {placeholder_role(name) for name in ("drone", "actioncam", "phone")}
    assert len(roles) == 3
    assert placeholder_role("reflex") == "thumb_neutral"
    assert placeholder_role("") == "thumb_neutral"
    for role in roles | {"thumb_neutral"}:
        assert getattr(tokens.DARK, role)


# --- and that it actually paints --------------------------------------------


def paint(grid: ThumbGrid, segment_id: str, selected: bool = False) -> QImage:
    size = grid.delegate.card_size()
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(0)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, size.width(), size.height())
    if selected:
        option.state |= QStyle.StateFlag.State_Selected
    painter = QPainter(image)
    grid.delegate.paint(painter, option, index_of(grid, segment_id))
    painter.end()
    return image


def painted_colours(image: QImage) -> set[str]:
    return {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    }


def test_a_card_is_actually_painted(grid: ThumbGrid) -> None:
    colours = painted_colours(paint(grid, "f0:0"))
    assert len(colours) > 3, colours


def test_a_drone_card_shows_the_drone_placeholder(grid: ThumbGrid) -> None:
    """No thumbnail exists in this project, so the tint is all the picture area has."""
    assert tokens.DARK.thumb_drone in painted_colours(paint(grid, "f0:0"))
    assert tokens.DARK.thumb_phone in painted_colours(paint(grid, "f2:0"))


def test_the_current_card_is_bordered_in_the_accent(grid: ThumbGrid) -> None:
    plain = painted_colours(paint(grid, "f1:0"))
    current = painted_colours(paint(grid, "f1:0", selected=True))
    assert tokens.DARK.accent in current
    assert tokens.DARK.border_strong in plain

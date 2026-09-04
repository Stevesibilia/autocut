"""The segment model and its filter proxy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from autocut.gui.models import (  # noqa: E402
    SegmentFilterProxy,
    SegmentListModel,
    SegmentRole,
    segment_duration,
)
from autocut.gui.state import ProjectState  # noqa: E402
from tests.unit.test_gui_state import a_manifest  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def opened(qtbot: Any, tmp_path: Path) -> ProjectState:
    """A state over a saved project of four candidates."""
    assert qtbot is not None
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    state = ProjectState()
    state.open_project(out)
    return state


def test_the_model_has_a_row_per_segment(opened: ProjectState) -> None:
    model = SegmentListModel(opened)

    assert model.rowCount() == 4


def test_a_model_over_no_project_is_empty(qtbot: Any) -> None:
    assert qtbot is not None
    model = SegmentListModel(ProjectState())

    assert model.rowCount() == 0
    assert model.data(model.index(0, 0), SegmentRole.SEGMENT_ID) is None


def test_every_role_reads_the_segment(opened: ProjectState) -> None:
    model = SegmentListModel(opened)
    index = model.index(0, 0)

    assert model.data(index, SegmentRole.SEGMENT_ID) == "f0:0"
    assert model.data(index, SegmentRole.OUTCOME) == "candidate"
    assert model.data(index, SegmentRole.SOURCE_CLASS) == "actioncam"
    assert model.data(index, SegmentRole.DURATION) == pytest.approx(20.0)
    assert model.data(index, SegmentRole.START) == pytest.approx(0.0)
    assert model.data(index, SegmentRole.FILE_NAME) == "f0.MP4"
    assert model.data(index, SegmentRole.DOMINANT_TAG) == ""
    assert "f0.MP4" in model.data(index, int(Qt.ItemDataRole.DisplayRole))
    assert "f0:0" in model.data(index, int(Qt.ItemDataRole.ToolTipRole))


def test_selected_clips_lead_in_edit_order(opened: ProjectState) -> None:
    """The report orders a project this way, and two views of one project must agree."""
    model = SegmentListModel(opened)
    manifest = opened.manifest
    assert manifest is not None
    last = manifest.segments["f3:0"]
    last.outcome = "selected"
    last.order = 1

    opened.selection_changed.emit()

    assert model.data(model.index(0, 0), SegmentRole.SEGMENT_ID) == "f3:0"
    assert model.row_of("f3:0") == 0


def test_a_row_that_is_gone_reports_minus_one(opened: ProjectState) -> None:
    model = SegmentListModel(opened)

    assert model.row_of("nothing:9") == -1


def test_the_model_follows_a_segments_changed_signal(opened: ProjectState) -> None:
    model = SegmentListModel(opened)
    manifest = opened.manifest
    assert manifest is not None
    del manifest.segments["f0:0"]

    opened.segments_changed.emit([])

    assert model.rowCount() == 3


def test_the_role_names_are_exposed(opened: ProjectState) -> None:
    names = SegmentListModel(opened).roleNames()

    assert bytes(names[SegmentRole.SCORE]) == b"score"
    assert bytes(names[SegmentRole.DOMINANT_TAG]) == b"dominantTag"


def test_the_proxy_filters_by_outcome(opened: ProjectState) -> None:
    model = SegmentListModel(opened)
    manifest = opened.manifest
    assert manifest is not None
    manifest.segments["f1:0"].outcome = "selected"
    opened.segments_changed.emit([])
    proxy = SegmentFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_outcomes({"selected"})

    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(SegmentRole.SEGMENT_ID) == "f1:0"


def test_an_empty_outcome_filter_shows_everything(opened: ProjectState) -> None:
    proxy = SegmentFilterProxy()
    proxy.setSourceModel(SegmentListModel(opened))

    proxy.set_outcomes({"selected"})
    proxy.set_outcomes(set())

    assert proxy.rowCount() == 4


def test_the_proxy_filters_by_source_class_and_tag(opened: ProjectState) -> None:
    from autocut.core.manifest import Tag

    manifest = opened.manifest
    assert manifest is not None
    manifest.segments["f2:0"].tags = [
        Tag(label="beach", confidence=0.9, source="local", primary=True)
    ]
    model = SegmentListModel(opened)
    proxy = SegmentFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_tag("beach")
    assert proxy.rowCount() == 1

    proxy.set_tag("")
    proxy.set_source_classes({"drone"})
    assert proxy.rowCount() == 0


def test_the_proxy_sorts_by_a_role(opened: ProjectState) -> None:
    proxy = SegmentFilterProxy()
    proxy.setSourceModel(SegmentListModel(opened))

    proxy.sort_by(SegmentRole.SCORE, descending=True)

    scores = [proxy.index(row, 0).data(SegmentRole.SCORE) for row in range(proxy.rowCount())]
    assert scores == sorted(scores, reverse=True)


def test_the_duration_is_the_trimmed_one(opened: ProjectState) -> None:
    manifest = opened.manifest
    assert manifest is not None
    segment = manifest.segments["f0:0"]
    segment.trimmed_start_s = 2.0
    segment.trimmed_end_s = 5.0

    assert segment_duration(segment) == pytest.approx(3.0)


def test_an_untrimmed_segment_falls_back_to_its_own_bounds(opened: ProjectState) -> None:
    manifest = opened.manifest
    assert manifest is not None
    segment = manifest.segments["f0:0"]
    segment.trimmed_start_s = None
    segment.trimmed_end_s = None

    assert segment_duration(segment) == pytest.approx(20.0)

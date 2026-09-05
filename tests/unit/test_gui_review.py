"""The Review screen: the grid, the filters, the decisions, the sliders and the groups."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autocut.core.cache import CacheEntry, write_entry  # noqa: E402
from autocut.core.config import AutocutConfig  # noqa: E402
from autocut.core.manifest import (  # noqa: E402
    GpsPoint,
    Manifest,
    Metrics,
    PlaceInfo,
    Segment,
    SourceFile,
    Tag,
)
from autocut.gui.screens.review import ReviewScreen  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from autocut.gui.widgets.groups import build_groups  # noqa: E402
from autocut.gui.widgets.preview import snap  # noqa: E402
from autocut.gui.widgets.scrubber import SpriteStrip  # noqa: E402
from autocut.gui.widgets.topbar import duration_label  # noqa: E402

pytestmark = pytest.mark.gui


#: Two spots five kilometres apart, so the places come out of the real grouping code
#: rather than being written onto the segments by hand.
SPOTS = ((40.1200, 9.6700), (40.2000, 8.5000))


def write_cache(out: Path, config: AutocutConfig, clips: int) -> None:
    """A cache entry per file, so selection can cluster and place them for real.

    Without entries ``select_clips`` finds no frames, no telemetry and no similarity,
    and it clears the cluster and place ids it cannot compute. Writing the entries is
    what makes the groups view and the place filter testable on a synthetic project.
    """
    for index in range(clips):
        frames = 40
        # The first three files look alike, so similarity puts them in one cluster.
        shade = 40 if index < 3 else 40 + 25 * index
        picture = np.full((16, 16, 3), min(shade, 250), dtype=np.uint8)
        lat, lon = SPOTS[0 if index < 4 else 1]
        write_entry(
            CacheEntry(
                file_key=f"f{index}",
                source="original",
                arrays={
                    "timestamps": np.arange(frames, dtype=np.float64) / 2.0,
                    "sharpness": np.full(frames, 100.0 + index),
                    "clipping": np.zeros(frames),
                    "motion": np.full(frames, 0.3),
                    "stability": np.full(frames, 0.9),
                    "colorfulness": np.full(frames, 0.2),
                },
                shot_bounds=[(0.0, 20.0)],
                telemetry=[{"time_s": 0.0, "lat": lat, "lon": lon}],
                thumb_frames=np.stack([picture]),
            ),
            config,
        )


def build_project(out: Path, clips: int = 8) -> Manifest:
    """A reviewable project: scored candidates, two places, two clusters, one rejection."""
    now = datetime.now(UTC)
    out.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(created_at=now, updated_at=now, sources=[out], output_dir=out)
    for index in range(clips):
        file_id = f"f{index}"
        lat, lon = SPOTS[0 if index < 4 else 1]
        manifest.files[file_id] = SourceFile(
            id=file_id,
            path=out / f"{file_id}.MP4",
            source_class="drone" if index % 4 == 0 else "actioncam",
            duration_s=60.0,
            width=1920,
            height=1080,
            fps=25.0,
            codec="h264",
            pix_fmt="yuv420p",
            gps=GpsPoint(lat=lat, lon=lon),
            created_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC) + timedelta(minutes=30 * index),
        )
        segment = Segment(
            id=f"{file_id}:0",
            file_id=file_id,
            start_s=0.0,
            end_s=20.0,
            trimmed_start_s=1.0,
            trimmed_end_s=19.0,
            best_center_s=10.0,
            # Not monotonic in capture order, so chronology and score are two orders.
            score=0.45 + ((index * 7) % 10) / 20,
            outcome="candidate",
            tags=[Tag(label="beach" if index % 2 else "mountain", confidence=0.8, primary=True)],
            metrics=Metrics(
                sharpness=100.0 + index,
                exposure_clipped=0.0,
                motion=0.3,
                stability=0.9,
                colorfulness=0.2,
            ),
        )
        manifest.segments[segment.id] = segment
    # One clip the rules threw out, which the grid hides until asked.
    thrown_out = manifest.segments[f"f{clips - 1}:0"]
    thrown_out.outcome = "rejected"
    thrown_out.reason = "blurry"
    manifest.save(out / "manifest.json")
    return manifest


def name_places(manifest: Manifest) -> None:
    """Give the places found by selection the names a geocode would have added."""
    names = ["Cala Goloritze", "Bosa", "Alghero", "Orgosolo"]
    for position, place_id in enumerate(
        sorted(
            {
                segment.place_id
                for segment in manifest.segments.values()
                if segment.place_id is not None
            }
        )
    ):
        manifest.places[str(place_id)] = PlaceInfo(
            place_id=place_id, name=names[position % len(names)]
        )


def reviewable(tmp_path: Path, out: Path, clips: int = 8) -> ProjectState:
    """A state over a selected project, with the cache selection needs."""
    build_project(out, clips)
    state = ProjectState()
    state.config.cache.dir = tmp_path / "cache"
    write_cache(out, state.config, clips)
    state.open_project(out)
    # After opening, not before: open_project reads autocut.toml beside the manifest
    # and replaces the configuration, which would undo anything set up here.
    state.config.cache.dir = tmp_path / "cache"
    state.config.selection.min_temporal_gap_seconds = 0.0
    state.config.selection.max_candidate_share = 0.0
    state.config.selection.max_clips = 3
    state.config.selection.max_clips_per_cluster = 3
    state.config.selection.max_clips_per_place = 3
    state.run_selection()
    manifest = state.manifest
    assert manifest is not None
    name_places(manifest)
    return state


@pytest.fixture
def screen(qtbot: Any, tmp_path: Path) -> ReviewScreen:
    state = reviewable(tmp_path, tmp_path / "edit")
    widget = ReviewScreen(state)
    qtbot.addWidget(widget)
    widget.resize(1200, 780)
    return widget


# --- the grid -----------------------------------------------------------------


def test_the_grid_shows_every_clip_the_rules_kept(screen: ReviewScreen) -> None:
    """Seven candidates; the eighth was rejected by a rule and is hidden by default."""
    assert screen.grid.count == 7
    assert not screen.grid.proxy.show_rejected


def test_the_rejected_clips_can_be_revealed(screen: ReviewScreen) -> None:
    screen.show_rejected.setChecked(True)

    assert screen.grid.count == 8
    assert "f7:0" in screen.grid.visible_ids()


def counter(screen: ReviewScreen, label: str) -> str:
    """The value of one top bar counter, by the word under it."""
    return next(c.value for c in screen.bar_counters() if c.label == label)


def test_the_counters_count_the_edit_and_not_the_filter(screen: ReviewScreen) -> None:
    """The scenario from the spec: filter to one place, the counters stay project wide."""
    assert counter(screen, "clips") == "3"
    manifest = screen._state.manifest
    assert manifest is not None
    place = sorted({s.place_id for s in manifest.segments.values() if s.place_id is not None})[0]

    screen.place_box.setCurrentIndex(screen.place_box.findData(place))

    shown = screen.grid.visible_ids()
    assert shown
    assert all(manifest.segments[sid].place_id == place for sid in shown)
    assert len(shown) < 7
    assert counter(screen, "clips") == "3"


def test_the_place_filter_names_the_place(screen: ReviewScreen) -> None:
    assert screen.place_box.findText("Cala Goloritze") >= 0


def test_the_class_and_tag_filters_narrow_the_grid(screen: ReviewScreen) -> None:
    screen.class_box.setCurrentIndex(screen.class_box.findData("drone"))
    drones = screen.grid.count

    screen.class_box.setCurrentIndex(0)
    screen.tag_box.setCurrentIndex(screen.tag_box.findData("beach"))

    assert drones == 2
    assert 0 < screen.grid.count < 7


def test_the_score_range_filters(screen: ReviewScreen) -> None:
    screen.min_score.setValue(0.8)

    ids = screen.grid.visible_ids()
    scores = [screen._state.segment(sid).score or 0.0 for sid in ids]  # type: ignore[union-attr]
    assert scores
    assert all(score >= 0.8 for score in scores)


def test_the_reason_filter_reveals_what_the_rules_did(screen: ReviewScreen) -> None:
    screen.reason_box.setCurrentIndex(screen.reason_box.findData("blurry"))

    assert screen.grid.visible_ids() == ["f7:0"]


def test_sorting_by_score_and_by_chronology(screen: ReviewScreen) -> None:
    """Two orders over the same clips, and the score one is actually ordered by score."""
    screen.sort_box.setCurrentIndex(1)
    by_score = screen.grid.visible_ids()
    screen.sort_box.setCurrentIndex(0)
    by_time = screen.grid.visible_ids()

    scores = [screen._state.segment(sid).score or 0.0 for sid in by_score]  # type: ignore[union-attr]
    assert scores == sorted(scores, reverse=True)
    assert set(by_time) == set(by_score)
    # Two different orders over the same clips: chronology puts the selected ones in
    # edit order and the rest in capture order, which score ranking does not.
    assert by_time != by_score


# --- decisions ----------------------------------------------------------------


def test_rejecting_with_the_keyboard_re_runs_the_selection(screen: ReviewScreen) -> None:
    """The scenario from the spec: press R on a selected card and the edit changes."""
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    selected = next(s for s in manifest.segments.values() if s.outcome == "selected")
    assert screen.grid.select_segment(selected.id)

    screen.grid.keyPressEvent(_key(Qt.Key.Key_R))

    assert selected.user_decision == "reject"
    assert selected.outcome != "selected"
    assert sum(1 for s in manifest.segments.values() if s.outcome == "selected") == 3
    assert counter(screen, "kept · rejected").endswith("· 1")


def test_keeping_with_the_keyboard_pins_the_clip(screen: ReviewScreen) -> None:
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    worst = min(
        (s for s in manifest.segments.values() if s.outcome != "rejected"),
        key=lambda s: s.score or 0.0,
    )
    assert screen.grid.select_segment(worst.id)

    screen.grid.keyPressEvent(_key(Qt.Key.Key_K))

    assert worst.kept
    assert worst.outcome == "selected"


def test_space_toggles_a_keep_off_again(screen: ReviewScreen) -> None:
    state = screen._state
    segment = state.segment(screen.grid.visible_ids()[0])
    assert segment is not None
    assert screen.grid.select_segment(segment.id)

    screen.grid.keyPressEvent(_key(Qt.Key.Key_Space))
    assert segment.kept

    screen.grid.keyPressEvent(_key(Qt.Key.Key_Space))
    assert segment.user_decision is None


def test_undo_restores_the_previous_decision(screen: ReviewScreen) -> None:
    """The scenario from the spec: U puts back what was there before."""
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    segment = next(iter(manifest.segments.values()))
    assert screen.grid.select_segment(segment.id)

    screen.grid.keyPressEvent(_key(Qt.Key.Key_R))
    assert segment.user_decision == "reject"

    screen.grid.keyPressEvent(_key(Qt.Key.Key_U))

    assert segment.user_decision is None
    assert state.undo_stack.canRedo()


def test_undo_walks_back_through_several_decisions(screen: ReviewScreen) -> None:
    state = screen._state
    ids = screen.grid.visible_ids()[:3]
    for segment_id in ids:
        screen.grid.select_segment(segment_id)
        screen._decide("reject")
    assert all(state.segment(sid).user_rejected for sid in ids)  # type: ignore[union-attr]

    for _ in ids:
        screen.undo()

    assert all(state.segment(sid).user_decision is None for sid in ids)  # type: ignore[union-attr]


def test_the_buttons_do_what_the_keys_do(screen: ReviewScreen) -> None:
    state = screen._state
    segment = next(iter(state.manifest.segments.values()))  # type: ignore[union-attr]
    screen.grid.select_segment(segment.id)

    screen.keep_button.click()
    assert segment.kept

    screen.clear_button.click()
    assert segment.user_decision is None


def test_a_decision_keeps_the_cursor_near_the_hand(screen: ReviewScreen) -> None:
    """A reviewer working down the grid must not be sent back to the top by a reject."""
    ids = screen.grid.visible_ids()
    target = ids[3]
    screen.grid.select_segment(target)

    screen._decide("reject")

    assert screen.grid.current_id() == target


def test_no_decisions_while_a_stage_runs(screen: ReviewScreen, qtbot: Any) -> None:
    """The worker owns the manifest during a stage, so the screen must not write to it."""
    import threading

    state = screen._state
    gate = threading.Event()
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))
    qtbot.wait(30)
    segment = next(iter(state.manifest.segments.values()))  # type: ignore[union-attr]

    assert not screen.keep_button.isEnabled()
    assert not screen.grid.isEnabled()
    assert state.set_decision(segment.id, "keep") is False
    assert segment.user_decision is None

    gate.set()
    with qtbot.waitSignal(state.stage_finished, timeout=5000):
        pass
    # The signal comes from inside the thread's run, so the thread is still winding
    # down: a QThread collected while running makes Qt abort the process.
    assert state.wait_for_stage(10_000)
    assert screen.keep_button.isEnabled()


# --- sliders ------------------------------------------------------------------


def test_a_weight_change_re_scores_and_re_sorts_within_the_debounce(
    screen: ReviewScreen, qtbot: Any
) -> None:
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    screen.sort_box.setCurrentIndex(1)  # by score
    before = screen.grid.visible_ids()
    scores_before = [state.segment(sid).score for sid in before]  # type: ignore[union-attr]

    with qtbot.waitSignal(state.selection_changed, timeout=5000):
        screen.sliders.set_weight("motion", 3.0)
        screen.sliders.set_weight("sharpness", 0.0)

    scores_after = [state.segment(sid).score for sid in before]  # type: ignore[union-attr]
    assert scores_after != scores_before
    assert screen.grid.visible_ids() != before


def test_a_slider_drag_is_one_selection_and_not_forty(screen: ReviewScreen, qtbot: Any) -> None:
    """The debounce is the whole reason the sliders are affordable."""
    state = screen._state
    runs: list[int] = []
    state.selection_changed.connect(lambda: runs.append(1))

    for value in range(0, 60, 5):
        screen.sliders.set_diversity(value / 100)

    qtbot.wait(state.config.gui.slider_debounce_ms + 400)

    assert runs == [1]


def test_diversity_zero_is_pure_score_ranking(screen: ReviewScreen, qtbot: Any) -> None:
    """The scenario from the spec, with the caps that are still in force."""
    state = screen._state
    manifest = state.manifest
    assert manifest is not None

    with qtbot.waitSignal(state.selection_changed, timeout=5000):
        screen.sliders.set_diversity(0.0)

    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    ranked = sorted(
        (s for s in manifest.segments.values() if s.outcome != "rejected"),
        key=lambda s: -(s.score or 0.0),
    )
    assert {s.id for s in selected} == {s.id for s in ranked[: len(selected)]}


def test_the_slider_reset_goes_back_in_one_selection(screen: ReviewScreen, qtbot: Any) -> None:
    state = screen._state
    screen.sliders.set_weight("motion", 2.5)
    qtbot.wait(state.config.gui.slider_debounce_ms + 300)
    runs: list[int] = []
    state.selection_changed.connect(lambda: runs.append(1))

    screen.sliders.reset()

    assert screen.sliders.weight("motion") == pytest.approx(1.0)
    assert state.config.weights.motion == pytest.approx(1.0)
    assert runs == [1]


def test_a_kept_clip_survives_every_slider_position(screen: ReviewScreen, qtbot: Any) -> None:
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    worst = min(
        (s for s in manifest.segments.values() if s.outcome != "rejected"),
        key=lambda s: s.score or 0.0,
    )
    assert screen.grid.select_segment(worst.id)
    screen._decide("keep")

    for value in (0.0, 0.5, 1.0):
        with qtbot.waitSignal(state.selection_changed, timeout=5000):
            screen.sliders.set_diversity(value)
            state.request_reselect(immediate=True)
        assert worst.outcome == "selected", value


def test_a_small_project_re_selects_inline(screen: ReviewScreen) -> None:
    """Selection on a normal folder is under a second from cache, so no thread is used."""
    state = screen._state

    assert not state.reselect_needs_worker()
    assert state.run_selection()
    assert not state.is_running


def test_a_big_project_hands_the_selection_to_the_worker(screen: ReviewScreen, qtbot: Any) -> None:
    """The threshold from the design, measured rather than assumed."""
    state = screen._state
    state.config.gui.reselect_worker_threshold = 3

    assert state.reselect_needs_worker()
    with qtbot.waitSignal(state.stage_finished, timeout=10_000) as blocker:
        assert state.run_selection()

    assert blocker.args == ["selection"]
    manifest = state.manifest
    assert manifest is not None
    assert any(s.outcome == "selected" for s in manifest.segments.values())


# --- preview and bounds -------------------------------------------------------


def test_the_preview_follows_the_grid_cursor(screen: ReviewScreen) -> None:
    ids = screen.grid.visible_ids()
    screen.grid.select_segment(ids[2])

    assert screen.preview.segment_id == ids[2]
    assert screen.preview.title.text() != "Nothing selected"


def test_dragging_the_out_point_saves_hand_set_bounds(screen: ReviewScreen) -> None:
    """The scenario from the spec: drag out to 6.5 s and the card shows the new length.

    On a clip that is in the edit, because the duration reason is written by the
    duration pass, which only runs over the clips that were selected.
    """
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    segment_id = next(s.id for s in manifest.segments.values() if s.outcome == "selected")
    assert screen.grid.select_segment(segment_id)
    preview = screen.preview

    preview.start_slider.setValue(preview._to_slider(4.0))
    preview.end_slider.setValue(preview._to_slider(6.5))
    preview._commit_bounds()

    segment = state.segment(segment_id)
    assert segment is not None
    assert segment.user_bounds is not None
    assert segment.user_bounds == pytest.approx((4.0, 6.5))
    assert segment.duration_reason == "user"
    assert segment.target_duration_s == pytest.approx(2.5)


def test_bounds_snap_to_the_sampling_grid(screen: ReviewScreen) -> None:
    state = screen._state
    sample_fps = state.config.analysis.sample_fps
    segment_id = screen.grid.visible_ids()[0]
    screen.grid.select_segment(segment_id)

    screen.preview.start_slider.setValue(screen.preview._to_slider(4.31))
    screen.preview.end_slider.setValue(screen.preview._to_slider(7.77))
    start, end = screen.preview.bounds()

    step = 1.0 / sample_fps
    assert start == pytest.approx(snap(4.31, sample_fps))
    assert (start / step) == pytest.approx(round(start / step))
    assert (end / step) == pytest.approx(round(end / step))


def test_bounds_stay_inside_the_trimmed_span(screen: ReviewScreen) -> None:
    """The sliders cannot ask for footage the trim already took away."""
    screen.grid.select_segment(screen.grid.visible_ids()[0])

    screen.preview.start_slider.setValue(0)
    screen.preview.end_slider.setValue(1000)
    start, end = screen.preview.bounds()

    assert start >= 1.0
    assert end <= 19.0


def test_a_hair_of_a_drag_is_not_a_decision(screen: ReviewScreen) -> None:
    state = screen._state
    segment_id = screen.grid.visible_ids()[0]
    screen.grid.select_segment(segment_id)

    screen.preview.start_slider.setValue(screen.preview._to_slider(5.0))
    screen.preview.end_slider.setValue(screen.preview._to_slider(5.05))
    screen.preview._commit_bounds()

    assert state.segment(segment_id).user_bounds is None  # type: ignore[union-attr]
    assert "shorter than one sampled frame" in screen.preview.note.text()


def test_clearing_the_bounds_returns_the_clip_to_the_search(screen: ReviewScreen) -> None:
    state = screen._state
    segment_id = screen.grid.visible_ids()[0]
    screen.grid.select_segment(segment_id)
    screen.preview.start_slider.setValue(screen.preview._to_slider(4.0))
    screen.preview.end_slider.setValue(screen.preview._to_slider(6.5))
    screen.preview._commit_bounds()
    assert state.segment(segment_id).user_bounds is not None  # type: ignore[union-attr]

    screen.preview._clear_bounds()

    assert state.segment(segment_id).user_bounds is None  # type: ignore[union-attr]


def test_undo_puts_back_the_previous_bounds(screen: ReviewScreen) -> None:
    state = screen._state
    segment_id = screen.grid.visible_ids()[0]
    screen.grid.select_segment(segment_id)
    screen.preview.start_slider.setValue(screen.preview._to_slider(4.0))
    screen.preview.end_slider.setValue(screen.preview._to_slider(6.5))
    screen.preview._commit_bounds()

    screen.undo()

    assert state.segment(segment_id).user_bounds is None  # type: ignore[union-attr]


# --- groups -------------------------------------------------------------------


def test_the_groups_are_the_clusters_and_the_visits(screen: ReviewScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None

    groups = build_groups(manifest)

    kinds = {group.key.split(":")[0] for group in groups}
    assert kinds == {"cluster", "visit"}
    assert all(group.size >= 2 for group in groups)
    assert any(group.pick is not None for group in groups)


def test_a_group_of_one_is_not_a_duplicate(screen: ReviewScreen) -> None:
    manifest = screen._state.manifest
    assert manifest is not None
    for segment in manifest.segments.values():
        segment.cluster_id = None
        segment.visit_id = None
    only = next(iter(manifest.segments.values()))
    only.cluster_id = 9

    assert build_groups(manifest) == []


def test_clicking_a_clip_behind_the_pick_swaps_the_two(screen: ReviewScreen) -> None:
    """The scenario from the spec, in one undo step."""
    state = screen._state
    screen.groups_toggle.setChecked(True)
    card = next(card for card in screen.groups.cards if card.group.pick is not None)
    pick = card.group.pick
    assert pick is not None
    other = card.group.others[0]

    card._clicked(other.id)

    assert other.kept
    assert other.outcome == "selected"
    assert state.segment(pick.id).user_rejected  # type: ignore[union-attr]
    assert state.segment(pick.id).outcome != "selected"  # type: ignore[union-attr]

    screen.undo()

    assert other.user_decision is None
    assert state.segment(pick.id).user_decision is None  # type: ignore[union-attr]


def test_clicking_the_pick_itself_does_nothing(screen: ReviewScreen) -> None:
    screen.groups_toggle.setChecked(True)
    card = next(card for card in screen.groups.cards if card.group.pick is not None)
    pick = card.group.pick
    assert pick is not None

    card._clicked(pick.id)

    assert pick.user_decision is None
    assert not screen._state.undo_stack.canUndo()


def test_the_groups_mode_shows_the_group_view(screen: ReviewScreen) -> None:
    screen.groups_toggle.setChecked(True)
    assert screen.stack.currentWidget() is screen.groups
    assert screen.groups.group_count > 0

    screen.groups_toggle.setChecked(False)
    assert screen.stack.currentWidget() is screen.grid


# --- hover scrubbing ----------------------------------------------------------


def strip_in_cache(tmp_path: Path, state: ProjectState, file_id: str = "f0") -> None:
    """Give one file a cached sprite strip of eight distinguishable frames."""
    frames = [np.full((16, 16, 3), 30 * (index + 1), dtype=np.uint8) for index in range(8)]
    write_entry(
        CacheEntry(
            file_key=file_id,
            source="original",
            arrays={"timestamps": np.arange(8, dtype=np.float64) / 2.0},
            shot_bounds=[(0.0, 20.0)],
            sprites=[np.concatenate(frames, axis=1)],
        ),
        state.config,
    )


def test_moving_the_pointer_across_a_card_changes_the_frame(
    screen: ReviewScreen, tmp_path: Path
) -> None:
    """The scenario from the spec: left to right walks the segment start to end."""
    state = screen._state
    strip_in_cache(tmp_path, state)
    segment_id = "f0:0"
    assert screen.grid.select_segment(segment_id)

    screen.grid.hover(segment_id, 0.0)
    first = screen.grid.hovered_frame_index()
    screen.grid.hover(segment_id, 0.5)
    middle = screen.grid.hovered_frame_index()
    screen.grid.hover(segment_id, 0.99)
    last = screen.grid.hovered_frame_index()

    assert first == 0
    assert 0 < middle < last
    assert last == 7


def test_a_missing_strip_is_built_on_the_first_hover(screen: ReviewScreen, tmp_path: Path) -> None:
    state = screen._state
    strip_in_cache(tmp_path, state)
    segment = state.segment("f0:0")
    assert segment is not None
    assert segment.sprite is None

    screen.grid.hover("f0:0", 0.25)
    # The delegate builds the strip when it needs the frame, which is what a paint
    # does; offscreen, with no event loop spinning, the accessor is that trigger.
    assert screen.grid.hovered_frame_index() >= 0

    assert segment.sprite is not None
    assert Path(segment.sprite).exists()


def test_a_clip_without_a_cached_strip_keeps_its_thumbnail(screen: ReviewScreen) -> None:
    """A project analysed without sprites is not asked for a strip on every mouse move."""
    screen.grid.hover("f1:0", 0.5)

    assert screen.grid.hovered_frame_index() == -1
    assert screen._state.segment("f1:0").sprite is None  # type: ignore[union-attr]


def test_the_pointer_position_becomes_a_fraction_of_the_card(screen: ReviewScreen) -> None:
    index = screen.grid.proxy.index(0, 0)
    rect = screen.grid.visualRect(index)

    left = screen.grid._fraction_in(index, QPoint(rect.x() + 1, rect.y() + 5))
    right = screen.grid._fraction_in(index, QPoint(rect.right() - 1, rect.y() + 5))

    assert left < 0.1
    assert right > 0.9


def test_the_strip_slices_itself_into_frames() -> None:
    """The frame count comes from the geometry, so any sprite_max_frames works."""
    app = QApplication.instance()
    assert app is not None
    pixmap = QPixmap(160, 20)
    strip = SpriteStrip(pixmap)

    assert strip.count == 8
    assert strip.index_at(0.0) == 0
    assert strip.index_at(1.0) == 7
    assert strip.index_at(-5.0) == 0
    assert strip.frame(3).width() == 20


def test_an_empty_strip_has_no_frames() -> None:
    strip = SpriteStrip(QPixmap())

    assert strip.count == 0
    assert strip.frame_at(0.5).isNull()


# --- the report ---------------------------------------------------------------


def test_exporting_the_report_shows_the_review(screen: ReviewScreen) -> None:
    """The scenario from the spec: reject two clips, export, and the report says so."""
    ids = screen.grid.visible_ids()[:2]
    for segment_id in ids:
        screen.grid.select_segment(segment_id)
        screen._decide("reject")

    path = screen.export_report()

    assert path is not None
    html = path.read_text(encoding="utf-8")
    assert "user rejected" in html
    assert counter(screen, "kept · rejected").endswith("· 2")


def test_the_report_button_writes_beside_the_manifest(screen: ReviewScreen) -> None:
    written: list[str] = []
    screen.report_written.connect(written.append)

    screen.report_button.click()

    assert written
    assert Path(written[0]).name == "report.html"
    assert Path(written[0]).parent == screen._state.output_dir


def test_the_report_is_not_written_while_a_stage_runs(screen: ReviewScreen, qtbot: Any) -> None:
    import threading

    state = screen._state
    gate = threading.Event()
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))
    qtbot.wait(30)

    assert screen.export_report() is None

    gate.set()
    assert state.wait_for_stage(10_000)
    qtbot.wait(50)


# --- the montage --------------------------------------------------------------


@pytest.fixture
def real_state(tmp_path: Path, synthetic_dir: Path, qtbot: Any) -> ProjectState:
    """A selected project over three real synthetic clips."""
    from tests.unit.test_montage import CLIPS
    from tests.unit.test_montage import project as montage_project_manifest

    assert qtbot is not None
    manifest = montage_project_manifest(tmp_path, CLIPS, synthetic_dir)
    manifest.save(tmp_path / "edit" / "manifest.json")
    state = ProjectState()
    state.open_project(tmp_path / "edit")
    state.config.cache.dir = tmp_path / "cache"
    # Off, or rejecting one of three clips would take the candidate ceiling to one and
    # the test would be measuring the selection rather than the montage.
    state.config.selection.max_candidate_share = 0.0
    state.config.selection.min_temporal_gap_seconds = 0.0
    return state


@pytest.mark.ffmpeg
def test_play_all_renders_once_and_plays(real_state: ProjectState, qtbot: Any) -> None:
    """The scenario from the spec, at three clips: render, play, follow the clips."""
    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    screen.resize(1200, 780)

    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000) as blocker:
        assert screen.play_all()

    assert blocker.args == ["montage"]
    assert screen.stack.currentWidget() is screen.montage
    assert len(screen.montage.parts) == 3
    assert real_state.manifest is not None
    assert real_state.manifest.preview.fingerprint is not None
    assert "3 clips" in screen.montage_note.text()

    # A second Play all on an untouched edit renders nothing at all.
    stamp = Path(real_state.manifest.preview.path).stat().st_mtime_ns  # type: ignore[arg-type]
    assert screen.play_all()
    assert not real_state.is_running
    assert Path(real_state.manifest.preview.path).stat().st_mtime_ns == stamp  # type: ignore[arg-type]


@pytest.mark.ffmpeg
def test_the_grid_follows_the_playing_clip(real_state: ProjectState, qtbot: Any) -> None:
    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        screen.play_all()
    second = screen.montage.parts[1].segment_id

    screen.montage.clip_changed.emit(second)

    assert screen.grid.current_id() == second
    assert screen.preview.segment_id == second


@pytest.mark.ffmpeg
def test_rejecting_while_playing_hits_the_clip_on_screen(
    real_state: ProjectState, qtbot: Any
) -> None:
    """The scenario from the spec: R during clip 2 rejects clip 2, not the grid cursor."""
    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        screen.play_all()
    playing = screen.montage.parts[1].segment_id
    # The grid cursor is somewhere else on purpose.
    screen.grid.select_segment(screen.montage.parts[0].segment_id)
    screen.montage.seek_to_clip(2)
    qtbot.waitUntil(
        lambda: screen.montage.current_segment_id() == playing,
        timeout=20_000,
    )

    screen._decide("reject")

    segment = real_state.segment(playing)
    assert segment is not None
    assert segment.user_rejected
    # Playback is not interrupted, and the montage is marked stale rather than rebuilt.
    assert "no longer matches the edit" in screen.montage_note.text()
    assert screen.montage.path is not None


@pytest.mark.ffmpeg
def test_a_decision_makes_the_montage_stale(real_state: ProjectState, qtbot: Any) -> None:
    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        screen.play_all()
    assert real_state.montage_is_current(None)

    screen.grid.select_segment(screen.montage.parts[0].segment_id)
    screen._decide("reject")

    assert not real_state.montage_is_current(None)
    assert "no longer matches" in screen.montage_note.text()


@pytest.mark.ffmpeg
def test_play_all_again_after_a_decision_rebuilds(real_state: ProjectState, qtbot: Any) -> None:
    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        screen.play_all()
    first = Path(real_state.manifest.preview.path)  # type: ignore[arg-type]
    # The montage is on screen, so a decision applies to the clip playing, which is
    # the first one: that is the behaviour this screen is built around.
    rejected = screen.montage.current_segment_id() or screen.montage.parts[0].segment_id
    screen._decide("reject")
    assert real_state.segment(rejected).user_rejected  # type: ignore[union-attr]

    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        assert screen.play_all()

    assert len(screen.montage.parts) == 2
    # A new edit is a new file, and the old one goes once the player has switched.
    assert screen.montage.path != first
    assert not first.exists()
    assert real_state.montage_is_current(None)


@pytest.mark.ffmpeg
def test_a_rebuild_writes_a_new_file_and_frees_the_old_one(
    real_state: ProjectState, qtbot: Any
) -> None:
    """Issue 43: a rebuild used to overwrite the file the player still had open.

    What came out was a stream of ``Invalid NAL unit size`` and a black picture. The
    montage is named after its fingerprint now, so a new edit is a new file, and the
    old one goes only once the player has been pointed at the new one.
    """
    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        assert screen.play_all()
    assert real_state.wait_for_stage(30_000)
    first = screen.montage.path
    assert first is not None
    assert first.exists()
    assert "montage-" in first.name

    screen.grid.select_segment(screen.montage.parts[0].segment_id)
    screen._decide("reject")
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        assert screen.play_all()
    assert real_state.wait_for_stage(30_000)

    second = screen.montage.path
    assert second is not None
    assert second != first
    assert second.exists()
    # The old file is gone, and it went after the player had let go of it.
    assert not first.exists()
    assert real_state.manifest is not None
    assert Path(real_state.manifest.preview.path) == second  # type: ignore[arg-type]


@pytest.mark.ffmpeg
def test_the_player_is_unloaded_before_the_rebuild_starts(
    real_state: ProjectState, qtbot: Any
) -> None:
    """The player lets go before anything writes: that is what kept the old file safe."""
    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        assert screen.play_all()
    assert real_state.wait_for_stage(30_000)
    assert screen.montage.path is not None

    screen.grid.select_segment(screen.montage.parts[0].segment_id)
    screen._decide("reject")
    assert screen.play_all()

    # While the render runs the player holds nothing at all.
    assert screen.montage.path is None
    assert screen.montage.parts == []
    assert real_state.wait_for_stage(180_000)


@pytest.mark.ffmpeg
def test_the_header_shows_the_edit_and_not_the_montage(
    real_state: ProjectState, qtbot: Any
) -> None:
    """Two durations one line apart read as one number contradicting itself."""
    from autocut.core.durations import total_duration

    screen = ReviewScreen(real_state)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(real_state.stage_finished, timeout=180_000):
        assert screen.play_all()
    assert real_state.wait_for_stage(30_000)
    manifest = real_state.manifest
    assert manifest is not None
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]

    edit = counter(screen, "edit")
    note = screen.montage_note.text()

    assert edit == duration_label(total_duration(selected))
    # The montage's own length lives in the transport row, not under the header.
    assert f"{manifest.preview.duration_s:.1f}" not in note
    assert "Montage of" in note
    assert f"{manifest.preview.duration_s:.1f}" in screen.montage.status.text()


def test_play_all_with_nothing_selected_says_why(screen: ReviewScreen, qtbot: Any) -> None:
    """The stage runs, finds nothing to render, and the screen reports the reason."""
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    for segment in manifest.segments.values():
        segment.outcome = "candidate"
        segment.order = None

    with qtbot.waitSignal(state.stage_finished, timeout=30_000):
        assert screen.play_all()

    assert state.wait_for_stage(10_000)
    assert "nothing is selected" in screen.montage_note.text()
    assert screen.stack.currentWidget() is not screen.montage


def test_switching_to_groups_pauses_the_montage(screen: ReviewScreen) -> None:
    """Leaving the montage is what stops it: nobody watches a montage behind a grid."""
    screen.groups_toggle.setChecked(True)

    assert screen.stack.currentWidget() is screen.groups

    screen.show_grid()
    assert screen.stack.currentWidget() is screen.grid


# --- opening another project --------------------------------------------------


def test_the_screen_follows_a_different_project(
    screen: ReviewScreen, tmp_path: Path, qtbot: Any
) -> None:
    other = tmp_path / "other"
    build_project(other, clips=4)
    state = screen._state
    write_cache(other, state.config, 4)

    state.open_project(other)
    state.config.selection.min_temporal_gap_seconds = 0.0
    state.run_selection()

    # Four clips, one of which the rules rejected and the grid hides.
    assert screen.grid.count == 3
    # The filters were rebuilt for this project: it has places of its own.
    assert screen.place_box.count() >= 2
    assert screen.bar_counters()


def test_an_empty_state_says_so(qtbot: Any) -> None:
    state = ProjectState()
    widget = ReviewScreen(state)
    qtbot.addWidget(widget)

    assert widget.grid.count == 0
    assert widget.bar_counters() == []


def _key(key: Qt.Key) -> Any:
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


def test_the_header_warns_when_the_pins_outgrow_the_cap(screen: ReviewScreen) -> None:
    state = screen._state
    manifest = state.manifest
    assert manifest is not None
    state.config.selection.max_clips = 2
    for segment in list(manifest.segments.values())[:4]:
        if segment.outcome != "rejected":
            screen.grid.select_segment(segment.id)
            screen._decide("keep")

    assert "longer than the settings ask for" in screen.warning.text()


def test_a_review_is_saved_without_being_asked(screen: ReviewScreen, qtbot: Any) -> None:
    """Autosave is the state's, and a decision has to reach the disk on its own."""
    state = screen._state
    segment_id = screen.grid.visible_ids()[0]
    screen.grid.select_segment(segment_id)

    started = time.monotonic()
    screen._decide("reject")
    with qtbot.waitSignal(state.saved, timeout=5000):
        pass

    reloaded = Manifest.load(state.output_dir / "manifest.json")  # type: ignore[operator]
    assert reloaded.segments[segment_id].user_decision == "reject"
    assert time.monotonic() - started < 5.0

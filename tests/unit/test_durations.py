"""Per-clip durations: every scenario in specs/clip-durations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.durations import (
    LONG,
    SHORT,
    assign_durations,
    base_duration,
    bucket,
    buckets,
    heroes,
    score_factor,
    shortfall,
    total_duration,
)
from autocut.core.manifest import Manifest, Segment, SourceFile


def project(tmp_path: Path) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(created_at=now, updated_at=now, sources=[Path("/f")], output_dir=tmp_path)


def add_file(manifest: Manifest, file_id: str, source_class: str = "drone") -> SourceFile:
    source = SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=60.0,
        width=1920,
        height=1080,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
    )
    manifest.files[file_id] = source
    return source


def add_clip(
    manifest: Manifest,
    segment_id: str,
    source_class: str = "drone",
    score: float = 0.5,
    span: float = 30.0,
    order: int | None = None,
) -> Segment:
    """One selected clip, with its own file so the class is per clip."""
    file_id = segment_id.partition(":")[0]
    if file_id not in manifest.files:
        add_file(manifest, file_id, source_class)
    segment = Segment(
        id=segment_id,
        file_id=file_id,
        start_s=0.0,
        end_s=span,
        trimmed_start_s=0.0,
        trimmed_end_s=span,
        score=score,
        outcome="selected",
        order=order if order is not None else len(manifest.segments) + 1,
    )
    manifest.segments[segment_id] = segment
    return segment


def selection(manifest: Manifest) -> list[Segment]:
    return [s for s in manifest.segments.values() if s.outcome == "selected"]


def no_variety(config: AutocutConfig) -> AutocutConfig:
    """Isolate the base rule from the heroes and the alternation pass."""
    config.selection.hero_share = 0.0
    config.selection.alternate_durations = False
    return config


# --- base duration by class, scaled by score ---------------------------------


def test_a_strong_drone_clip(tmp_path: Path) -> None:
    """The scenario in specs/clip-durations: score 1.0 on the defaults gives 4.8 s."""
    manifest = project(tmp_path)
    clip = add_clip(manifest, "a:0", "drone", score=1.0)
    assign_durations(selection(manifest), manifest, no_variety(AutocutConfig()))
    assert clip.target_duration_s == pytest.approx(4.8)
    assert clip.duration_reason == "base"


def test_a_weak_action_cam_clip(tmp_path: Path) -> None:
    """The scenario in specs/clip-durations: score 0.0 gives 1.6 s."""
    manifest = project(tmp_path)
    clip = add_clip(manifest, "a:0", "actioncam", score=0.0)
    assign_durations(selection(manifest), manifest, no_variety(AutocutConfig()))
    assert clip.target_duration_s == pytest.approx(1.6)


def test_a_segment_shorter_than_its_target(tmp_path: Path) -> None:
    """The scenario in specs/clip-durations: a 1.4 s phone shot keeps its 1.4 s."""
    manifest = project(tmp_path)
    clip = add_clip(manifest, "a:0", "phone", score=0.5, span=1.4)
    assign_durations(selection(manifest), manifest, no_variety(AutocutConfig()))
    assert clip.target_duration_s == pytest.approx(1.4)
    assert clip.duration_reason == "clamped"


def test_the_score_moves_the_duration_between_the_two_ends() -> None:
    config = no_variety(AutocutConfig())
    assert score_factor(0.0, config) == pytest.approx(0.8)
    assert score_factor(0.5, config) == pytest.approx(1.0)
    assert score_factor(1.0, config) == pytest.approx(1.2)
    # A missing or out of range score cannot push the factor outside the range.
    assert score_factor(None, config) == pytest.approx(0.8)
    assert score_factor(2.0, config) == pytest.approx(1.2)


def test_each_class_starts_from_its_own_base(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index, source_class in enumerate(("drone", "actioncam", "phone", "reflex", "generic")):
        add_clip(manifest, f"c{index}:0", source_class, score=0.5)
    assign_durations(selection(manifest), manifest, no_variety(AutocutConfig()))
    durations = {s.id: s.target_duration_s for s in selection(manifest)}
    assert durations["c0:0"] == pytest.approx(4.0)
    assert durations["c1:0"] == pytest.approx(2.0)
    assert durations["c2:0"] == pytest.approx(2.5)
    assert durations["c3:0"] == pytest.approx(3.0)
    assert durations["c4:0"] == pytest.approx(3.0)


def test_a_class_with_no_base_falls_back_to_the_project_duration(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    clip = add_clip(manifest, "a:0", "drone", score=0.5)
    config = no_variety(AutocutConfig())
    config.selection.duration_by_class.drone = 0.0
    config.selection.target_duration_seconds = 3.0
    assign_durations(selection(manifest), manifest, config)
    assert base_duration(manifest, clip, config) == 3.0
    assert clip.target_duration_s == pytest.approx(3.0)


def test_the_configured_bounds_hold(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    long_clip = add_clip(manifest, "a:0", "drone", score=1.0)
    config = no_variety(AutocutConfig())
    config.selection.duration_max_seconds = 4.0
    assign_durations(selection(manifest), manifest, config)
    assert long_clip.target_duration_s == pytest.approx(4.0)
    # A configured bound is a setting, not a surprise, so it does not claim the reason.
    assert long_clip.duration_reason == "base"


# --- heroes ------------------------------------------------------------------


def test_four_heroes_in_forty(tmp_path: Path) -> None:
    """The scenario in specs/clip-durations, with the default 10 percent share."""
    manifest = project(tmp_path)
    for index in range(40):
        add_clip(manifest, f"c{index}:0", "drone", score=index / 39.0, order=index + 1)
    config = AutocutConfig()
    config.selection.alternate_durations = False
    chosen = selection(manifest)
    assign_durations(chosen, manifest, config)

    heroic = [s for s in chosen if s.duration_reason == "hero"]
    assert len(heroic) == 4
    assert {s.id for s in heroic} == {f"c{index}:0" for index in (36, 37, 38, 39)}
    for segment in heroic:
        assert segment.target_duration_s is not None
        assert segment.target_duration_s <= config.selection.duration_max_seconds


def test_a_hero_is_the_base_result_times_the_multiplier(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(10):
        add_clip(manifest, f"c{index}:0", "actioncam", score=index / 9.0, order=index + 1)
    config = AutocutConfig()
    config.selection.alternate_durations = False
    assign_durations(selection(manifest), manifest, config)
    # 2.0 base at score 1.0 is 2.4, and the hero bonus makes it 3.6.
    best = manifest.segments["c9:0"]
    assert best.duration_reason == "hero"
    assert best.target_duration_s == pytest.approx(3.6)


def test_a_selection_too_small_for_a_hero_has_none(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, "a:0", "drone", score=1.0)
    config = AutocutConfig()
    assert heroes(selection(manifest), config) == set()
    assign_durations(selection(manifest), manifest, config)
    assert manifest.segments["a:0"].duration_reason == "base"


def test_a_hero_clamped_by_the_maximum_is_still_a_hero(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(10):
        add_clip(manifest, f"c{index}:0", "drone", score=index / 9.0, order=index + 1)
    config = AutocutConfig()
    config.selection.alternate_durations = False
    assign_durations(selection(manifest), manifest, config)
    best = manifest.segments["c9:0"]
    # 4.0 base at score 1.0 is 4.8, times 1.5 is 7.2, held at the 6.0 maximum.
    assert best.target_duration_s == pytest.approx(6.0)
    assert best.duration_reason == "hero"


# --- alternation -------------------------------------------------------------


def test_three_long_in_a_row(tmp_path: Path) -> None:
    """The scenario in specs/clip-durations: the middle of three is shortened."""
    manifest = project(tmp_path)
    for index in range(3):
        add_clip(manifest, f"c{index}:0", "drone", score=1.0, order=index + 1)
    config = no_variety(AutocutConfig())
    config.selection.alternate_durations = True
    assign_durations(selection(manifest), manifest, config)

    middle = manifest.segments["c1:0"]
    assert middle.duration_reason == "alternation"
    assert middle.target_duration_s == pytest.approx(4.8 * 0.75)
    assert manifest.segments["c0:0"].target_duration_s == pytest.approx(4.8)
    assert manifest.segments["c2:0"].target_duration_s == pytest.approx(4.8)


def test_three_short_in_a_row_are_lengthened(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(3):
        add_clip(manifest, f"c{index}:0", "actioncam", score=0.0, order=index + 1)
    config = no_variety(AutocutConfig())
    config.selection.alternate_durations = True
    assign_durations(selection(manifest), manifest, config)

    middle = manifest.segments["c1:0"]
    assert middle.duration_reason == "alternation"
    assert middle.target_duration_s == pytest.approx(1.6 * 1.25)


def test_a_hero_in_the_middle_is_protected(tmp_path: Path) -> None:
    """The scenario in specs/clip-durations: the third clip is shortened instead."""
    manifest = project(tmp_path)
    # Ten clips so the 10 percent share picks exactly one hero, placed in the middle
    # of the first run of three.
    for index in range(10):
        add_clip(manifest, f"c{index}:0", "drone", score=0.9, order=index + 1)
    manifest.segments["c1:0"].score = 1.0
    config = AutocutConfig()
    assign_durations(selection(manifest), manifest, config)

    assert manifest.segments["c1:0"].duration_reason == "hero"
    assert manifest.segments["c2:0"].duration_reason == "alternation"


def test_alternation_never_shortens_below_the_floor(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(3):
        add_clip(manifest, f"c{index}:0", "actioncam", score=1.0, order=index + 1)
    config = no_variety(AutocutConfig())
    config.selection.alternate_durations = True
    config.selection.duration_min_seconds = 2.2
    assign_durations(selection(manifest), manifest, config)
    for segment in selection(manifest):
        assert segment.target_duration_s is not None
        assert segment.target_duration_s >= 2.2


def test_alternation_never_exceeds_the_trimmed_span(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(3):
        add_clip(manifest, f"c{index}:0", "actioncam", score=0.0, span=1.7, order=index + 1)
    config = no_variety(AutocutConfig())
    config.selection.alternate_durations = True
    assign_durations(selection(manifest), manifest, config)
    for segment in selection(manifest):
        assert segment.target_duration_s is not None
        assert segment.target_duration_s <= 1.7


def test_a_mixed_run_is_left_alone(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, "c0:0", "drone", score=1.0, order=1)
    add_clip(manifest, "c1:0", "drone", score=0.0, order=2)
    add_clip(manifest, "c2:0", "drone", score=1.0, order=3)
    config = no_variety(AutocutConfig())
    config.selection.alternate_durations = True
    assign_durations(selection(manifest), manifest, config)
    assert all(s.duration_reason == "base" for s in selection(manifest))


def test_alternation_walks_chronological_order_not_insertion_order(tmp_path: Path) -> None:
    """The rhythm is what the viewer sees, so the pass follows the edit order."""
    manifest = project(tmp_path)
    add_clip(manifest, "c0:0", "drone", score=1.0, order=3)
    add_clip(manifest, "c1:0", "drone", score=1.0, order=1)
    add_clip(manifest, "c2:0", "drone", score=1.0, order=2)
    config = no_variety(AutocutConfig())
    config.selection.alternate_durations = True
    assign_durations(selection(manifest), manifest, config)
    # Order 2 is the middle of the run, whichever order the clips were added in.
    assert manifest.segments["c2:0"].duration_reason == "alternation"


def test_alternation_can_be_switched_off(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(3):
        add_clip(manifest, f"c{index}:0", "drone", score=1.0, order=index + 1)
    assign_durations(selection(manifest), manifest, no_variety(AutocutConfig()))
    assert all(s.duration_reason == "base" for s in selection(manifest))


# --- total target ------------------------------------------------------------


def test_a_ninety_second_edit(tmp_path: Path) -> None:
    """The scenario in specs/clip-durations: 40 clips at 3.0 s scaled onto 90 s."""
    manifest = project(tmp_path)
    for index in range(40):
        add_clip(manifest, f"c{index}:0", "generic", score=0.5, order=index + 1)
    config = no_variety(AutocutConfig())
    config.selection.target_total_seconds = 90.0
    chosen = selection(manifest)
    assign_durations(chosen, manifest, config)

    total = total_duration(chosen)
    assert total == pytest.approx(90.0, abs=90.0 * 0.05)
    assert 85.5 <= total <= 94.5
    assert all(s.duration_reason == "total" for s in chosen)
    assert manifest.selection.total_duration_s == pytest.approx(total, abs=0.01)


def test_the_total_scale_keeps_the_relative_rhythm(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, "c0:0", "drone", score=0.5, order=1)
    add_clip(manifest, "c1:0", "actioncam", score=0.5, order=2)
    config = no_variety(AutocutConfig())
    # 6.0 s scaled onto 5.0 leaves both clips clear of the 1.5 s floor. A target that
    # pushes one onto a bound breaks the ratio, which is the clamps winning by design.
    config.selection.target_total_seconds = 5.0
    assign_durations(selection(manifest), manifest, config)
    drone = manifest.segments["c0:0"].target_duration_s
    action = manifest.segments["c1:0"].target_duration_s
    assert drone is not None and action is not None
    # 4.0 against 2.0 before, so still two to one after.
    assert drone / action == pytest.approx(2.0)


def test_a_total_the_clamps_cannot_reach_is_reported(tmp_path: Path) -> None:
    """The bounds win, and the shortfall is reported rather than clips dropped."""
    manifest = project(tmp_path)
    for index in range(10):
        add_clip(manifest, f"c{index}:0", "drone", score=0.5, order=index + 1)
    config = no_variety(AutocutConfig())
    # Ten clips cannot go below the 1.5 s floor, so 5 s is out of reach.
    config.selection.target_total_seconds = 5.0
    chosen = selection(manifest)
    assign_durations(chosen, manifest, config)

    assert total_duration(chosen) == pytest.approx(15.0)
    assert shortfall(chosen, config) == pytest.approx(-10.0)
    for segment in chosen:
        assert segment.target_duration_s == pytest.approx(1.5)


def test_no_total_target_means_no_shortfall(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, "a:0", "drone", score=0.5)
    config = no_variety(AutocutConfig())
    chosen = selection(manifest)
    assign_durations(chosen, manifest, config)
    assert shortfall(chosen, config) == 0.0


# --- override ----------------------------------------------------------------


def test_the_uniform_override(tmp_path: Path) -> None:
    """The legacy behaviour scenario: --duration 3.0 gives 3.0 everywhere."""
    manifest = project(tmp_path)
    for index, source_class in enumerate(("drone", "actioncam", "phone")):
        add_clip(manifest, f"c{index}:0", source_class, score=index / 2.0, order=index + 1)
    chosen = selection(manifest)
    assign_durations(chosen, manifest, AutocutConfig(), override=3.0)

    for segment in chosen:
        assert segment.target_duration_s == pytest.approx(3.0)
        assert segment.duration_reason == "override"
    assert manifest.selection.total_duration_s == pytest.approx(9.0)


def test_the_override_still_respects_a_short_shot(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    clip = add_clip(manifest, "a:0", "phone", score=0.5, span=1.2)
    assign_durations(selection(manifest), manifest, AutocutConfig(), override=3.0)
    assert clip.target_duration_s == pytest.approx(1.2)
    assert clip.duration_reason == "override"


def test_the_override_skips_heroes_and_alternation(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(10):
        add_clip(manifest, f"c{index}:0", "drone", score=index / 9.0, order=index + 1)
    chosen = selection(manifest)
    assign_durations(chosen, manifest, AutocutConfig(), override=3.0)
    assert {s.duration_reason for s in chosen} == {"override"}
    assert {s.target_duration_s for s in chosen} == {3.0}


# --- recorded and reported ---------------------------------------------------


def test_the_total_is_recorded_on_the_manifest(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(3):
        add_clip(manifest, f"c{index}:0", "generic", score=0.5, order=index + 1)
    chosen = selection(manifest)
    assign_durations(chosen, manifest, no_variety(AutocutConfig()))
    assert manifest.selection.total_duration_s == pytest.approx(total_duration(chosen))


def test_the_bucket_counts_are_reportable(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(10):
        add_clip(manifest, f"c{index}:0", "drone", score=index / 9.0, order=index + 1)
    config = AutocutConfig()
    chosen = selection(manifest)
    assign_durations(chosen, manifest, config)

    counts = buckets(chosen, manifest, config)
    assert counts[LONG] + counts[SHORT] == 10
    assert counts["hero"] == 1


def test_bucketing_is_relative_to_the_class_base() -> None:
    """A 2.0 s action clip and a 4.0 s drone clip are both ordinary, not short and long."""
    assert bucket(2.0, 2.0) == LONG
    assert bucket(4.0, 4.0) == LONG
    assert bucket(1.9, 2.0) == SHORT
    assert bucket(3.9, 4.0) == SHORT


def test_an_empty_selection_records_a_zero_total(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    assign_durations([], manifest, AutocutConfig())
    assert manifest.selection.total_duration_s == 0.0

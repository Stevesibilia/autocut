"""Pins and hand set bounds: what a person said, and what no automatic step may undo."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autocut.core.beatsync import quantize_durations, reset_final_bounds
from autocut.core.config import AutocutConfig
from autocut.core.durations import assign_durations
from autocut.core.ffmpeg_cmd import plan_export
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile
from autocut.core.select import select_clips


def settings() -> AutocutConfig:
    config = AutocutConfig()
    # Off unless a test asks for them, so a pin is tested against one rule at a time.
    config.selection.min_temporal_gap_seconds = 0.0
    config.selection.max_candidate_share = 0.0
    config.selection.hero_share = 0.0
    return config


def project(tmp_path: Path) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path)


def add_clip(
    manifest: Manifest,
    index: int,
    score: float,
    span: tuple[float, float] = (0.0, 20.0),
    source_class: str = "actioncam",
    fps: float = 25.0,
) -> Segment:
    """One candidate whose score is given rather than computed, so pins are visible."""
    file_id = f"f{index}"
    manifest.files[file_id] = SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=120.0,
        width=1920,
        height=1080,
        fps=fps,
        codec="h264",
        pix_fmt="yuv420p",
        created_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC) + timedelta(minutes=10 * index),
    )
    start, stop = span
    segment = Segment(
        id=f"{file_id}:0",
        file_id=file_id,
        start_s=start,
        end_s=stop,
        trimmed_start_s=start,
        trimmed_end_s=stop,
        best_center_s=(start + stop) / 2.0,
        score=score,
        outcome="candidate",
        metrics=Metrics(
            sharpness=100.0,
            exposure_clipped=0.0,
            motion=0.3,
            stability=0.9,
            colorfulness=0.2,
        ),
    )
    manifest.segments[segment.id] = segment
    return segment


# --- keep and reject pins -----------------------------------------------------


def test_a_kept_clip_is_selected_however_low_it_scores(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.9 - index / 100) for index in range(10)]
    worst = clips[-1]
    worst.user_decision = "keep"
    config = settings()
    config.selection.max_clips = 3

    result = select_clips(manifest, config)

    assert worst.outcome == "selected"
    assert result.kept == 1


def test_a_rejected_clip_is_never_selected_and_the_next_one_takes_the_slot(
    tmp_path: Path,
) -> None:
    """The scenario from the spec: reject the best, and the runner up is in the edit."""
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.9 - index / 100) for index in range(6)]
    best, runner_up = clips[0], clips[1]
    best.user_decision = "reject"
    config = settings()
    config.selection.max_clips = 2

    result = select_clips(manifest, config)

    assert best.outcome != "selected"
    assert runner_up.outcome == "selected"
    assert result.user_rejected == 1
    assert result.count == 2


def test_a_kept_clip_survives_the_diversity_slider(tmp_path: Path) -> None:
    """The scenario from the spec. The pin has to beat the similarity penalty too."""
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.9 - index / 100) for index in range(8)]
    pinned = clips[-1]
    pinned.user_decision = "keep"
    config = settings()
    config.selection.max_clips = 4

    for lam in (0.0, 0.5, 1.0, 2.0):
        config.selection.diversity_lambda = lam
        select_clips(manifest, config)
        assert pinned.outcome == "selected", lam


def test_pins_are_selected_first_and_the_rest_of_the_slots_are_filled_normally(
    tmp_path: Path,
) -> None:
    """The scenario from the modified clip-selection spec: three pins, ten slots."""
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.5 + index / 100) for index in range(20)]
    for clip in clips[:3]:
        clip.user_decision = "keep"
    config = settings()
    config.selection.max_clips = 10
    config.selection.max_clips_per_file.actioncam = 1

    result = select_clips(manifest, config)

    assert all(clip.outcome == "selected" for clip in clips[:3])
    assert result.count == 10
    assert result.kept == 3
    assert not result.kept_over_cap


def test_more_pins_than_slots_keeps_every_pin_and_says_so(tmp_path: Path) -> None:
    """Caps count pins but cannot drop them: a person asked for these clips by name."""
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.5) for index in range(6)]
    for clip in clips:
        clip.user_decision = "keep"
    config = settings()
    config.selection.max_clips = 2

    result = select_clips(manifest, config)

    assert result.count == 6
    assert result.kept == 6
    assert result.kept_over_cap
    assert all(clip.outcome == "selected" for clip in clips)


def test_a_pin_survives_a_second_select(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.9 - index / 100) for index in range(6)]
    clips[-1].user_decision = "keep"
    clips[0].user_decision = "reject"
    config = settings()
    config.selection.max_clips = 3

    select_clips(manifest, config)
    select_clips(manifest, config)

    assert clips[-1].outcome == "selected"
    assert clips[0].outcome != "selected"
    assert clips[-1].user_decision == "keep"
    assert clips[0].user_decision == "reject"


def test_clearing_a_keep_puts_the_clip_back_in_the_competition(tmp_path: Path) -> None:
    """The scenario from the spec: undo a keep, and it competes on score again."""
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.9 - index / 10) for index in range(6)]
    worst = clips[-1]
    worst.user_decision = "keep"
    config = settings()
    config.selection.max_clips = 2

    select_clips(manifest, config)
    assert worst.outcome == "selected"

    worst.user_decision = None
    result = select_clips(manifest, config)

    assert worst.outcome != "selected"
    assert result.kept == 0


def test_clearing_a_reject_lets_the_clip_win_again(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.9 - index / 10) for index in range(6)]
    best = clips[0]
    best.user_decision = "reject"
    config = settings()
    config.selection.max_clips = 2

    select_clips(manifest, config)
    assert best.outcome != "selected"

    best.user_decision = None
    select_clips(manifest, config)

    assert best.outcome == "selected"


def test_a_rejected_clip_does_not_count_towards_the_candidate_ceiling(
    tmp_path: Path,
) -> None:
    """The ceiling is a share of what could be picked, and a reject never can be."""
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.5 + index / 100) for index in range(10)]
    config = settings()
    config.selection.max_clips = 40
    config.selection.max_candidate_share = 0.5
    config.selection.max_clips_per_file.actioncam = 1

    before = select_clips(manifest, config).max_clips
    for clip in clips[:6]:
        clip.user_decision = "reject"
    after = select_clips(manifest, config).max_clips

    assert before == 5
    assert after == 2


def test_the_similarity_penalty_cannot_unpick_a_pin(tmp_path: Path) -> None:
    """Two identical shots, one pinned: the pin stays even at a punishing lambda."""
    manifest = project(tmp_path)
    first = add_clip(manifest, 1, score=0.9)
    second = add_clip(manifest, 2, score=0.2)
    second.user_decision = "keep"
    config = settings()
    config.selection.max_clips = 2
    config.selection.diversity_lambda = 5.0

    select_clips(manifest, config)

    assert first.outcome == "selected"
    assert second.outcome == "selected"


# --- hand set bounds ----------------------------------------------------------


def test_hand_set_bounds_become_the_length_and_the_reason(tmp_path: Path) -> None:
    """The scenario from the spec: in 4.0, out 6.5, reason user."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5, span=(0.0, 20.0))
    segment.user_start_s = 4.0
    segment.user_end_s = 6.5

    assign_durations([segment], manifest, settings())

    assert segment.target_duration_s == pytest.approx(2.5)
    assert segment.duration_reason == "user"


def test_hand_set_bounds_are_what_export_cuts(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5, span=(0.0, 20.0))
    segment.user_start_s = 4.0
    segment.user_end_s = 6.5
    segment.outcome = "selected"
    segment.order = 1
    source = manifest.files[segment.file_id]

    plan = plan_export(segment, source, manifest, settings())

    assert plan.source_start_s == pytest.approx(4.0)
    assert plan.source_duration_s == pytest.approx(2.5)
    assert plan.out_duration_s == pytest.approx(2.5)


def test_the_duration_flag_does_not_overrule_a_hand_trimmed_clip(tmp_path: Path) -> None:
    """``--duration`` is one length for every clip the machine chose, not for a decision."""
    manifest = project(tmp_path)
    automatic = add_clip(manifest, 1, score=0.5)
    by_hand = add_clip(manifest, 2, score=0.5)
    by_hand.user_start_s = 2.0
    by_hand.user_end_s = 5.0

    assign_durations([automatic, by_hand], manifest, settings(), override=3.5)

    assert automatic.target_duration_s == pytest.approx(3.5)
    assert automatic.duration_reason == "override"
    assert by_hand.target_duration_s == pytest.approx(3.0)
    assert by_hand.duration_reason == "user"


def test_the_hero_bonus_leaves_a_hand_trimmed_clip_alone(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    clips = [add_clip(manifest, index, score=0.9 - index / 100) for index in range(10)]
    best = clips[0]
    best.user_start_s = 1.0
    best.user_end_s = 2.0
    config = settings()
    config.selection.hero_share = 0.5

    assign_durations(clips, manifest, config)

    assert best.target_duration_s == pytest.approx(1.0)
    assert best.duration_reason == "user"


def test_beat_sync_quantizes_inside_the_hand_set_bounds(tmp_path: Path) -> None:
    """The bounds are the shot as far as sync is concerned: it may shorten, never extend."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5, span=(0.0, 30.0))
    segment.user_start_s = 10.0
    segment.user_end_s = 12.4
    segment.outcome = "selected"
    segment.order = 1
    segment.target_duration_s = 2.4
    config = settings()

    quantize_durations(manifest, 120.0, config)

    assert segment.beats == 4  # 2.0 s: six beats would need 3.0 s and there is 2.4
    assert segment.final_start_s is not None
    assert segment.final_end_s is not None
    assert segment.final_start_s >= 10.0
    assert segment.final_end_s <= 12.4


def test_beat_sync_centres_on_the_hand_set_middle(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5, span=(0.0, 30.0))
    # A centre the searched window would never have chosen.
    segment.best_center_s = 3.0
    segment.user_start_s = 20.0
    segment.user_end_s = 24.0
    segment.outcome = "selected"
    segment.order = 1
    segment.target_duration_s = 4.0

    quantize_durations(manifest, 120.0, settings())

    assert segment.final_start_s == pytest.approx(20.0)
    assert segment.final_end_s == pytest.approx(24.0)


def test_a_reset_of_the_sync_leaves_the_hand_set_bounds_alone(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5)
    segment.user_start_s = 2.0
    segment.user_end_s = 5.0

    reset_final_bounds(manifest)

    assert segment.user_start_s == pytest.approx(2.0)
    assert segment.user_end_s == pytest.approx(5.0)


def test_selection_does_not_search_a_window_for_a_hand_trimmed_clip(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5, span=(0.0, 20.0))
    segment.user_start_s = 8.0
    segment.user_end_s = 11.0

    select_clips(manifest, settings())

    assert segment.best_center_s == pytest.approx(9.5)
    assert segment.target_duration_s == pytest.approx(3.0)


# --- the shape of a half finished decision ------------------------------------


def test_one_bound_alone_is_not_a_decision(tmp_path: Path) -> None:
    """A half finished drag must not become a one sided window."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5)

    segment.user_start_s = 3.0
    assert segment.user_bounds is None

    segment.user_end_s = 3.0
    assert segment.user_bounds is None  # zero length is not a clip either

    segment.user_end_s = 4.0
    assert segment.user_bounds == (3.0, 4.0)


def test_the_effective_bounds_prefer_the_hand_set_ones(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5, span=(1.0, 9.0))

    assert segment.effective_bounds == (1.0, 9.0)
    assert segment.effective_center == pytest.approx(5.0)

    segment.user_start_s = 2.0
    segment.user_end_s = 4.0

    assert segment.effective_bounds == (2.0, 4.0)
    assert segment.effective_center == pytest.approx(3.0)


def test_the_decision_survives_a_round_trip_through_the_manifest(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, score=0.5)
    segment.user_decision = "keep"
    segment.user_start_s = 2.0
    segment.user_end_s = 5.0
    path = tmp_path / "manifest.json"
    manifest.save(path)

    loaded = Manifest.load(path)

    restored = loaded.segments[segment.id]
    assert restored.user_decision == "keep"
    assert restored.user_bounds == (2.0, 5.0)
    assert restored.kept
    assert not restored.user_rejected

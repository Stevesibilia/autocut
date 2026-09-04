"""Beat sync: the tempo comparison, the rounding rule, the bounds and the beat map."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.beatsync import (
    BEATMAP_FILENAME,
    Track,
    bpm_from_beats,
    choose_multiple,
    compare_bpm,
    quantize_durations,
    reset_final_bounds,
    snap_to_grid,
    write_beatmap,
)
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile


def project(tmp_path: Path) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path)


def add_clip(
    manifest: Manifest,
    order: int,
    target: float,
    span: tuple[float, float] = (0.0, 20.0),
    centre: float | None = None,
    source_class: str = "actioncam",
    fps: float = 25.0,
    score: float = 0.5,
) -> Segment:
    file_id = f"f{order}"
    manifest.files[file_id] = SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=60.0,
        width=1920,
        height=1080,
        fps=fps,
        codec="h264",
        pix_fmt="yuv420p",
    )
    start, stop = span
    segment = Segment(
        id=f"{file_id}:0",
        file_id=file_id,
        start_s=start,
        end_s=stop,
        trimmed_start_s=start,
        trimmed_end_s=stop,
        best_center_s=centre if centre is not None else (start + stop) / 2.0,
        target_duration_s=target,
        duration_reason="base",
        outcome="selected",
        order=order,
        score=score,
        metrics=Metrics(
            sharpness=100.0, exposure_clipped=0.0, motion=0.3, stability=0.9, colorfulness=0.2
        ),
    )
    manifest.segments[segment.id] = segment
    return segment


def settings(multiples: list[int] | None = None) -> AutocutConfig:
    config = AutocutConfig()
    if multiples is not None:
        config.soundtrack.beat_multiples = multiples
    # No heroes unless a test asks for them, so the tie break is tested deliberately.
    config.selection.hero_share = 0.0
    return config


def test_the_shipped_multiples_are_half_a_bar_to_four_bars() -> None:
    """The first version stopped at 8 and left a 6 s hero clip nowhere to land."""
    assert AutocutConfig().soundtrack.beat_multiples == [2, 4, 6, 8, 12, 16]


def test_two_point_two_seconds_at_120_becomes_four_beats(tmp_path: Path) -> None:
    """The scenario from the spec, and unchanged by the wider multiples list."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.2)

    quantize_durations(manifest, 120.0, settings())

    assert segment.beats == 4
    assert segment.target_duration_s == pytest.approx(2.0)
    assert segment.duration_reason == "beat"


def test_a_hero_takes_the_longer_side_of_a_tie(tmp_path: Path) -> None:
    """At 120 with the shipped multiples, 2.5 s sits exactly between 4 and 6 beats.

    The spec's own example, a 3.0 s hero, is no longer a tie: 6 beats is in the list and
    3.0 s is exactly six of them. This is the tie the shipped list actually produces.
    """
    manifest = project(tmp_path)
    hero = add_clip(manifest, 1, target=2.5, score=0.99)
    other = add_clip(manifest, 2, target=2.5, score=0.1)
    config = settings()
    config.selection.hero_share = 0.5

    quantize_durations(manifest, 120.0, config)

    assert hero.beats == 6
    assert hero.target_duration_s == pytest.approx(3.0)
    assert other.beats == 4
    assert other.target_duration_s == pytest.approx(2.0)


def test_a_six_second_hero_now_lands_on_twelve_beats(tmp_path: Path) -> None:
    """The clip that motivated the change: 6 s at 120 is 12 beats, and 12 is legal now."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=6.0, span=(0.0, 30.0))

    quantize_durations(manifest, 120.0, settings())

    assert segment.beats == 12
    assert segment.target_duration_s == pytest.approx(6.0)


def test_the_same_clip_under_the_old_multiples_was_four_beats_out(tmp_path: Path) -> None:
    """Why the default changed, as an assertion rather than a claim."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=6.0, span=(0.0, 30.0))

    quantize_durations(manifest, 120.0, settings([2, 4, 8]))

    assert segment.beats == 8
    assert segment.target_duration_s == pytest.approx(4.0)


def test_a_short_span_falls_back_to_a_smaller_multiple(tmp_path: Path) -> None:
    """The scenario from the spec: a 1.6 s span cannot hold 2.0 s, so two beats it is."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.2, span=(0.0, 1.6))

    result = quantize_durations(manifest, 120.0, settings())

    assert segment.beats == 2
    assert segment.target_duration_s == pytest.approx(1.0)
    assert result.clamped == 1


def test_a_span_shorter_than_the_smallest_multiple_gives_the_span(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.0, span=(0.0, 0.6))

    result = quantize_durations(manifest, 120.0, settings())

    assert segment.target_duration_s == pytest.approx(0.6)
    assert result.clamped == 1


def test_the_alternation_survives_the_rounding(tmp_path: Path) -> None:
    """Rounding each clip around its own value keeps long and short alternating."""
    manifest = project(tmp_path)
    targets = [4.1, 1.9, 4.2, 2.1, 3.9, 2.0]
    clips = [add_clip(manifest, index + 1, target=value) for index, value in enumerate(targets)]

    quantize_durations(manifest, 120.0, settings())

    beats = [clip.beats for clip in clips]
    assert beats == [8, 4, 8, 4, 8, 4]


def test_final_bounds_are_centred_on_the_best_window(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.0, span=(0.0, 20.0), centre=10.0)

    quantize_durations(manifest, 120.0, settings())

    assert segment.final_start_s == pytest.approx(9.0)
    assert segment.final_end_s == pytest.approx(11.0)
    assert segment.final_end_s - segment.final_start_s == pytest.approx(2.0)


def test_final_bounds_stay_inside_the_trimmed_span(tmp_path: Path) -> None:
    """A centre near the end must not put the window past the end of the shot."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.0, span=(5.0, 8.0), centre=7.8)

    quantize_durations(manifest, 120.0, settings())

    assert segment.final_start_s >= 5.0
    assert segment.final_end_s <= 8.0
    assert segment.final_end_s - segment.final_start_s == pytest.approx(2.0)


def test_final_bounds_sit_on_the_sampling_grid(tmp_path: Path) -> None:
    """Cutting between two sampled frames is cutting where nothing was measured."""
    manifest = project(tmp_path)
    config = settings()
    segment = add_clip(manifest, 1, target=2.0, span=(0.0, 20.0), centre=10.3)

    quantize_durations(manifest, 120.0, config)

    grid = 1.0 / config.analysis.sample_fps
    assert segment.final_start_s is not None
    assert segment.final_start_s / grid == pytest.approx(round(segment.final_start_s / grid))


def test_a_slowed_clip_reads_less_source_than_it_plays(tmp_path: Path) -> None:
    """A 50 fps action cam at a 25 fps target plays two seconds from one of source.

    The target frame rate is the one most clips reach by whole-number division, so the
    project needs 25 fps clips in it: a project of nothing but 50 fps footage is a 50 fps
    project and slows nothing down.
    """
    manifest = project(tmp_path)
    for index in range(3):
        add_clip(manifest, index + 2, target=2.0, fps=25.0)
    segment = add_clip(manifest, 1, target=2.0, span=(0.0, 20.0), centre=10.0, fps=50.0)
    config = settings()
    assert config.export.slow_motion_auto.get("actioncam")

    quantize_durations(manifest, 120.0, config)

    assert segment.target_duration_s == pytest.approx(2.0)
    assert segment.final_end_s - segment.final_start_s == pytest.approx(1.0)


def test_the_result_reports_the_distribution_and_the_drift(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index, target in enumerate([2.2, 2.2, 4.1], start=1):
        add_clip(manifest, index, target=target)

    result = quantize_durations(manifest, 120.0, settings())

    assert result.clips == 3
    assert result.per_multiple == {4: 2, 8: 1}
    assert result.total_before_s == pytest.approx(8.5)
    assert result.total_after_s == pytest.approx(8.0)
    assert result.drift_s == pytest.approx(-0.5)
    assert result.mean_shift_s > 0


def test_a_project_with_nothing_selected_quantizes_nothing(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, 1, target=2.0).outcome = "candidate"

    assert quantize_durations(manifest, 120.0, settings()).clips == 0


def test_a_zero_bpm_does_nothing(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.2)

    assert quantize_durations(manifest, 0.0, settings()).clips == 0
    assert segment.beats is None


def test_a_re_run_starts_from_the_assigned_durations(tmp_path: Path) -> None:
    """The scenario from the spec: syncing at 110 then 124 reflects 124, not both."""
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.2)

    quantize_durations(manifest, 110.0, settings())
    first = segment.target_duration_s
    # A re-run quantizes what the edit assigned, so the caller restores it; the CLI does
    # this by resetting the bounds and re-running select's durations. Here the point is
    # that reset clears the marks a second pass must not inherit.
    reset_final_bounds(manifest)
    assert segment.final_start_s is None
    assert segment.beats is None

    segment.target_duration_s = 2.2
    quantize_durations(manifest, 124.0, settings())

    assert segment.beats == 4
    assert segment.target_duration_s == pytest.approx(4 * 60 / 124)
    assert segment.target_duration_s != first


def test_the_tempo_comparison_agrees_within_tolerance() -> None:
    result = compare_bpm(120.0, 121.5, 3.0)

    assert result.status == "agreed"
    assert result.agreed


def test_a_drifted_track_names_both_numbers() -> None:
    """The scenario from the spec: proposed 120, measured 126, tolerance 3."""
    result = compare_bpm(120.0, 126.0, 3.0)

    assert result.status == "drifted"
    assert not result.agreed
    assert result.note is not None
    assert "126" in result.note
    assert "120" in result.note


def test_a_half_tempo_track_says_so_and_offers_the_flag() -> None:
    """The scenario from the spec: proposed 120, measured 60."""
    result = compare_bpm(120.0, 60.0, 3.0)

    assert result.status == "half"
    assert result.note is not None
    assert "half" in result.note
    assert "--bpm 120" in result.note


def test_a_double_tempo_track_says_so() -> None:
    result = compare_bpm(120.0, 240.0, 3.0)

    assert result.status == "double"
    assert result.note is not None
    assert "--bpm 120" in result.note


def test_no_proposal_is_not_a_disagreement() -> None:
    """Sync works without the soundtrack step, and says the comparison was skipped."""
    result = compare_bpm(None, 128.0, 3.0)

    assert result.status == "no proposal"
    assert result.agreed


def test_choosing_the_nearest_multiple() -> None:
    multiples = [2, 4, 6, 8, 12, 16]

    assert choose_multiple(4.4, multiples, round_up_on_tie=False) == 4
    assert choose_multiple(5.6, multiples, round_up_on_tie=False) == 6
    assert choose_multiple(100.0, multiples, round_up_on_tie=False) == 16
    assert choose_multiple(0.1, multiples, round_up_on_tie=False) == 2
    # Exactly between 4 and 6.
    assert choose_multiple(5.0, multiples, round_up_on_tie=False) == 4
    assert choose_multiple(5.0, multiples, round_up_on_tie=True) == 6


def test_an_empty_multiples_list_falls_back_to_a_bar() -> None:
    assert choose_multiple(3.0, [], round_up_on_tie=False) == 4


def test_snapping_to_the_grid() -> None:
    assert snap_to_grid(10.3, 2.0) == pytest.approx(10.5)
    assert snap_to_grid(10.2, 2.0) == pytest.approx(10.0)
    assert snap_to_grid(10.3, 0.0) == pytest.approx(10.3)


def test_the_tempo_comes_from_the_beat_spacing_not_the_estimate() -> None:
    """librosa places beats on 23 ms frames, so the gaps alternate around the truth."""
    alternating = [0.0]
    for index in range(20):
        alternating.append(alternating[-1] + (0.4876 if index % 2 else 0.5109))

    assert bpm_from_beats(alternating, fallback=117.5) == pytest.approx(120.0, abs=0.5)


def test_a_missed_beat_does_not_drag_the_tempo() -> None:
    clean = [index * 0.5 for index in range(20)]
    missed = [moment for index, moment in enumerate(clean) if index != 10]

    assert bpm_from_beats(missed, fallback=0.0) == pytest.approx(120.0)


def test_too_few_beats_falls_back_to_the_estimate() -> None:
    assert bpm_from_beats([], fallback=118.0) == 118.0
    assert bpm_from_beats([1.0], fallback=118.0) == 118.0


def test_the_beat_map_lists_the_beats_and_the_clip_starts(tmp_path: Path) -> None:
    """The scenario from the spec, at the size a real edit has."""
    manifest = project(tmp_path)
    for index in range(29):
        add_clip(manifest, index + 1, target=2.0)
    quantize_durations(manifest, 120.0, settings())
    track = Track(bpm=120.0, beats_s=[index * 0.5 for index in range(40)], duration_s=20.0)

    path = write_beatmap(manifest, track, tmp_path)

    assert path.name == BEATMAP_FILENAME
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "120 bpm, 40 beats" in lines[0]
    # Forty beat times, then a section with one line per clip.
    assert sum(1 for line in lines if line and not line.startswith("#") and " " not in line) == 40
    clip_lines = [line for line in lines if "actioncam" in line]
    assert len(clip_lines) == 29
    assert clip_lines[0].split()[1] == "0.000"
    assert clip_lines[1].split()[1] == "2.000"
    assert "edit length 58.000 s" in text


def test_the_beat_map_names_the_clips(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, 1, target=2.0)
    quantize_durations(manifest, 120.0, settings())

    text = write_beatmap(manifest, Track(bpm=120.0), tmp_path).read_text(encoding="utf-8")

    assert "actioncam" in text
    assert ".mp4" in text


def test_resetting_forgets_a_previous_sync(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    segment = add_clip(manifest, 1, target=2.2)
    quantize_durations(manifest, 120.0, settings())
    assert segment.final_start_s is not None

    reset_final_bounds(manifest)

    assert segment.final_start_s is None
    assert segment.final_end_s is None
    assert segment.beats is None


def test_the_beat_seconds_of_a_track() -> None:
    assert Track(bpm=120.0).beat_seconds == pytest.approx(0.5)
    assert Track(bpm=0.0).beat_seconds == 0.0


def test_the_measured_bpm_is_not_the_librosa_estimate() -> None:
    """Kept apart on the Track so the CLI can say when the two disagree."""
    track = Track(bpm=120.0, tempo_estimate=117.5)

    assert track.bpm != track.tempo_estimate


def test_quantizing_leaves_unselected_clips_alone(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    kept = add_clip(manifest, 1, target=2.2)
    dropped = add_clip(manifest, 2, target=2.2)
    dropped.outcome = "candidate"

    quantize_durations(manifest, 120.0, settings())

    assert kept.beats == 4
    assert dropped.beats is None
    assert dropped.target_duration_s == pytest.approx(2.2)
    assert np.isclose(dropped.final_start_s or -1, -1)

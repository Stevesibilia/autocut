"""Selection over synthetic manifests: every scenario in specs/clip-selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile, Tag
from autocut.core.select import SelectionOverrides, absolute_time, select_clips
from autocut.core.similarity import SimilarityMatrix

DAY = datetime(2025, 7, 14, 13, 0, tzinfo=UTC)


def project(tmp_path: Path) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(created_at=now, updated_at=now, sources=[Path("/f")], output_dir=tmp_path)


def add_file(
    manifest: Manifest,
    file_id: str,
    source_class: str = "drone",
    minutes: float = 0.0,
    gps: tuple[float, float] | None = None,
) -> SourceFile:
    from autocut.core.manifest import GpsPoint

    source = SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=30.0,
        width=1920,
        height=1080,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
        creation_time=DAY + timedelta(minutes=minutes),
        gps=GpsPoint(lat=gps[0], lon=gps[1]) if gps else None,
    )
    manifest.files[file_id] = source
    return source


def add_segment(
    manifest: Manifest,
    segment_id: str,
    file_id: str,
    score: float,
    start: float = 0.0,
    end: float = 20.0,
    outcome: str = "candidate",
    reason: str | None = None,
) -> Segment:
    segment = Segment(
        id=segment_id,
        file_id=file_id,
        start_s=start,
        end_s=end,
        trimmed_start_s=start,
        trimmed_end_s=end,
        score=score,
        outcome=outcome,  # type: ignore[arg-type]
        reason=reason,
        metrics=Metrics(
            sharpness=100.0, exposure_clipped=0.0, motion=0.3, stability=0.9, colorfulness=0.2
        ),
    )
    manifest.segments[segment_id] = segment
    return segment


def no_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the score and cap logic from similarity."""
    monkeypatch.setattr(SimilarityMatrix, "between", lambda self, a, b: 1.0 if a == b else 0.0)


def fixed_similarity(monkeypatch: pytest.MonkeyPatch, pairs: dict[frozenset[str], float]) -> None:
    def between(self: SimilarityMatrix, a: str, b: str) -> float:
        if a == b:
            return 1.0
        return pairs.get(frozenset({a, b}), 0.0)

    monkeypatch.setattr(SimilarityMatrix, "between", between)


def open_config() -> AutocutConfig:
    """Caps out of the way, so a test exercises one constraint at a time."""
    config = AutocutConfig()
    config.selection.min_temporal_gap_seconds = 0.0
    config.selection.max_clips_per_cluster = 99
    config.selection.max_clips_per_place = 99
    # The share ceiling would otherwise bound max_clips in every test that sets it.
    config.selection.max_candidate_share = 1.0
    for name in ("drone", "actioncam", "phone", "reflex", "generic"):
        setattr(config.selection.max_clips_per_file, name, 99)
    return config


def selected_ids(manifest: Manifest) -> list[str]:
    return sorted(s.id for s in manifest.segments.values() if s.outcome == "selected")


def test_near_duplicates_lose_to_a_different_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_similarity(monkeypatch, {frozenset({"a:0", "b:0"}): 0.9})
    manifest = project(tmp_path)
    for name in ("a", "b", "c"):
        add_file(manifest, name)
    add_segment(manifest, "a:0", "a", 0.90)
    add_segment(manifest, "b:0", "b", 0.85)
    add_segment(manifest, "c:0", "c", 0.60)

    config = open_config()
    config.selection.diversity_lambda = 0.6
    config.selection.max_clips = 2
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["a:0", "c:0"]


def test_lambda_zero_selects_by_score_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_similarity(monkeypatch, {frozenset({"a:0", "b:0"}): 0.9})
    manifest = project(tmp_path)
    for name in ("a", "b", "c"):
        add_file(manifest, name)
    add_segment(manifest, "a:0", "a", 0.90)
    add_segment(manifest, "b:0", "b", 0.85)
    add_segment(manifest, "c:0", "c", 0.60)

    config = open_config()
    config.selection.diversity_lambda = 0.0
    config.selection.max_clips = 2
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["a:0", "b:0"]


def test_rejected_segments_are_never_eligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", 0.99, outcome="rejected", reason="shaky")
    add_segment(manifest, "a:1", "a", 0.10, start=20.0, end=30.0)

    config = open_config()
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["a:1"]
    assert manifest.segments["a:0"].outcome == "rejected"
    assert manifest.segments["a:0"].reason == "shaky"


def test_per_file_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a", "drone")
    add_segment(manifest, "a:0", "a", 0.9, 0.0, 5.0)
    add_segment(manifest, "a:1", "a", 0.8, 5.0, 10.0)
    add_segment(manifest, "a:2", "a", 0.7, 10.0, 15.0)

    config = open_config()
    config.selection.max_clips_per_file.drone = 1
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["a:0"]


def test_class_share_reserves_slots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(10):
        add_file(manifest, f"d{index}", "drone", minutes=index)
        add_segment(manifest, f"d{index}:0", f"d{index}", 0.9)
    for index in range(3):
        add_file(manifest, f"p{index}", "phone", minutes=30 + index)
        add_segment(manifest, f"p{index}:0", f"p{index}", 0.1)

    config = open_config()
    config.selection.max_clips = 10
    config.selection.min_share_per_class.phone = 0.2
    select_clips(manifest, config)

    phones = [s for s in manifest.segments.values() if s.outcome == "selected" and "p" in s.file_id]
    assert len(phones) >= 2


def test_a_share_larger_than_the_class_takes_what_there_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(9):
        add_file(manifest, f"d{index}", "drone", minutes=index)
        add_segment(manifest, f"d{index}:0", f"d{index}", 0.9)
    add_file(manifest, "p0", "phone", minutes=40)
    add_segment(manifest, "p0:0", "p0", 0.1)

    config = open_config()
    config.selection.max_clips = 10
    config.selection.min_share_per_class.phone = 0.3
    result = select_clips(manifest, config)

    assert manifest.segments["p0:0"].outcome == "selected"
    assert result.count == 10


def test_minimum_temporal_gap_skips_a_neighbour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a", "drone", minutes=0.0)
    add_file(manifest, "b", "drone", minutes=20.0 / 60.0)
    add_file(manifest, "c", "drone", minutes=10.0)
    add_segment(manifest, "a:0", "a", 0.95, 0.0, 4.0)
    add_segment(manifest, "b:0", "b", 0.90, 0.0, 4.0)
    add_segment(manifest, "c:0", "c", 0.50, 0.0, 4.0)

    config = open_config()
    config.selection.min_temporal_gap_seconds = 60.0
    config.selection.max_clips = 2
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["a:0", "c:0"]


def test_the_gap_is_relaxed_when_nothing_else_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a", "drone", minutes=0.0)
    add_file(manifest, "b", "drone", minutes=20.0 / 60.0)
    add_segment(manifest, "a:0", "a", 0.95, 0.0, 4.0)
    add_segment(manifest, "b:0", "b", 0.90, 0.0, 4.0)

    config = open_config()
    config.selection.min_temporal_gap_seconds = 60.0
    config.selection.max_clips = 2
    result = select_clips(manifest, config)

    assert selected_ids(manifest) == ["a:0", "b:0"]
    assert result.relaxed_gap


def test_ordering_across_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Order follows absolute time, as the requirement text states.

    The scenario in specs/clip-selection lists the orders as "2, 1 and 3" for a
    phone clip at 13:39, a drone clip at 13:37 and an action cam clip at 13:38.
    Chronologically that is 3, 1 and 2, which is what the requirement itself asks
    for and what the ingest ordering scenario already established. The scenario
    numbers look like a transcription slip and the requirement wins.
    """
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "phone", "phone", minutes=39.0)
    add_file(manifest, "drone", "drone", minutes=37.0)
    add_file(manifest, "action", "actioncam", minutes=38.0)
    add_segment(manifest, "phone:0", "phone", 0.5, 0.0, 4.0)
    add_segment(manifest, "drone:0", "drone", 0.5, 0.0, 4.0)
    add_segment(manifest, "action:0", "action", 0.5, 0.0, 4.0)

    config = open_config()
    select_clips(manifest, config)

    assert manifest.segments["drone:0"].order == 1
    assert manifest.segments["action:0"].order == 2
    assert manifest.segments["phone:0"].order == 3


def test_a_losing_near_duplicate_names_its_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_similarity(monkeypatch, {frozenset({"a:0", "b:0"}): 0.9})
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_file(manifest, "b", minutes=10)
    add_segment(manifest, "a:0", "a", 0.90)
    add_segment(manifest, "b:0", "b", 0.85)

    config = open_config()
    config.selection.max_clips = 1
    config.selection.cluster_threshold = 0.75
    select_clips(manifest, config)

    loser = manifest.segments["b:0"]
    assert loser.outcome == "candidate"
    assert loser.lost_to == "a:0"
    assert loser.similarity_to_selected == pytest.approx(0.9)


def test_a_distant_candidate_records_similarity_without_losing_to_anyone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_similarity(monkeypatch, {frozenset({"a:0", "b:0"}): 0.2})
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_file(manifest, "b", minutes=10)
    add_segment(manifest, "a:0", "a", 0.90)
    add_segment(manifest, "b:0", "b", 0.85)

    config = open_config()
    config.selection.max_clips = 1
    select_clips(manifest, config)

    loser = manifest.segments["b:0"]
    assert loser.lost_to is None
    assert loser.similarity_to_selected == pytest.approx(0.2)


def test_cluster_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_similarity(
        monkeypatch,
        {
            frozenset({"a:0", "b:0"}): 0.9,
            frozenset({"a:0", "c:0"}): 0.9,
            frozenset({"b:0", "c:0"}): 0.9,
        },
    )
    manifest = project(tmp_path)
    for index, name in enumerate(("a", "b", "c", "d")):
        add_file(manifest, name, minutes=index * 10)
    add_segment(manifest, "a:0", "a", 0.90)
    add_segment(manifest, "b:0", "b", 0.88)
    add_segment(manifest, "c:0", "c", 0.86)
    add_segment(manifest, "d:0", "d", 0.10)

    config = open_config()
    config.selection.diversity_lambda = 0.0
    config.selection.max_clips_per_cluster = 2
    config.selection.max_clips = 4
    select_clips(manifest, config)

    chosen = selected_ids(manifest)
    assert "d:0" in chosen
    # a, b and c are one cluster, and only two of them may be taken.
    assert len([name for name in chosen if name in {"a:0", "b:0", "c:0"}]) == 2


def test_select_is_re_runnable_and_leaves_rejections_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_similarity(monkeypatch, {frozenset({"a:0", "b:0"}): 0.9})
    manifest = project(tmp_path)
    for index, name in enumerate(("a", "b", "c")):
        add_file(manifest, name, minutes=index * 10)
    add_segment(manifest, "a:0", "a", 0.90)
    add_segment(manifest, "b:0", "b", 0.85)
    add_segment(manifest, "c:0", "c", 0.60)
    add_segment(
        manifest, "c:1", "c", 0.99, start=20.0, end=30.0, outcome="rejected", reason="clipped"
    )

    config = open_config()
    config.selection.max_clips = 2

    select_clips(manifest, config, SelectionOverrides(diversity_lambda=0.0))
    assert selected_ids(manifest) == ["a:0", "b:0"]

    select_clips(manifest, config, SelectionOverrides(diversity_lambda=1.0))
    assert selected_ids(manifest) == ["a:0", "c:0"]

    assert manifest.segments["c:1"].outcome == "rejected"
    assert manifest.segments["c:1"].reason == "clipped"
    assert manifest.segments["c:1"].order is None


def test_the_run_records_its_parameters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", 0.9)

    config = open_config()
    select_clips(
        manifest,
        config,
        SelectionOverrides(max_clips=7, target_duration_s=2.0, diversity_lambda=0.25),
    )

    run = manifest.selection
    assert run.max_clips == 7
    assert run.target_duration_s == pytest.approx(2.0)
    assert run.diversity_lambda == pytest.approx(0.25)
    assert run.selected == 1
    assert run.ran_at is not None


def test_best_window_is_stored_on_every_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", 0.9, 1.0, 19.0)

    config = open_config()
    select_clips(manifest, config, SelectionOverrides(target_duration_s=3.0))

    segment = manifest.segments["a:0"]
    assert segment.target_duration_s == pytest.approx(3.0)
    assert segment.best_center_s is not None
    assert segment.best_center_s - 1.5 >= 1.0
    assert segment.best_center_s + 1.5 <= 19.0


def test_an_empty_manifest_selects_nothing(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    result = select_clips(manifest, AutocutConfig())
    assert result.count == 0
    assert manifest.selection.selected == 0


def test_absolute_time_is_creation_plus_window_offset(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    source = add_file(manifest, "a", minutes=0.0)
    segment = add_segment(manifest, "a:0", "a", 0.5)
    segment.best_center_s = 12.0
    assert absolute_time(source, segment) == DAY + timedelta(seconds=12)
    assert absolute_time(None, segment) is None


def test_no_video_is_decoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Selection reads cached arrays; a spawned ffmpeg would be a bug."""
    import subprocess

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("selection must not start a process")

    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "run", explode)

    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", 0.9)
    config = open_config()
    config.cache.dir = tmp_path / "cache"
    select_clips(manifest, config)
    assert selected_ids(manifest) == ["a:0"]


def test_selection_without_cache_entries_still_places_a_window(tmp_path: Path) -> None:
    """A manifest whose cache was pruned must still select, using segment midpoints."""
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", 0.9, 2.0, 8.0)
    config = open_config()
    config.cache.dir = tmp_path / "empty-cache"
    select_clips(manifest, config)

    segment = manifest.segments["a:0"]
    assert segment.best_center_s == pytest.approx(5.0)
    # The length still follows the class base and the score, cache or no cache: the
    # 4.0 s drone base at score 0.9 is 4.64, and the 6.0 s span leaves room for it.
    assert segment.target_duration_s == pytest.approx(4.64)
    assert segment.duration_reason == "base"
    assert np.isfinite(segment.best_center_s)


def test_a_share_is_a_floor_and_rounds_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fifth of nine clips is two clips: the share is a minimum, so it rounds up."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(9):
        add_file(manifest, f"d{index}", "drone", minutes=index)
        add_segment(manifest, f"d{index}:0", f"d{index}", 0.9)
    for index in range(3):
        add_file(manifest, f"p{index}", "phone", minutes=30 + index)
        add_segment(manifest, f"p{index}:0", f"p{index}", 0.1)

    config = open_config()
    config.selection.max_clips = 9
    config.selection.min_share_per_class.phone = 0.2
    result = select_clips(manifest, config)

    phones = sum(1 for s in manifest.segments.values() if s.outcome == "selected" and "p" in s.id)
    assert phones == 2
    assert result.count == 9


def test_generous_shares_never_overrun_the_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two classes asking for 60% each must still produce one edit of max_clips."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(10):
        add_file(manifest, f"d{index}", "drone", minutes=index)
        add_segment(manifest, f"d{index}:0", f"d{index}", 0.9)
    for index in range(10):
        add_file(manifest, f"p{index}", "phone", minutes=30 + index)
        add_segment(manifest, f"p{index}:0", f"p{index}", 0.1)

    config = open_config()
    config.selection.max_clips = 10
    config.selection.min_share_per_class.drone = 0.6
    config.selection.min_share_per_class.phone = 0.6
    result = select_clips(manifest, config)

    assert result.count == 10
    assert len(selected_ids(manifest)) == 10


def vertical_file(manifest: Manifest, file_id: str, minutes: float = 0.0) -> None:
    """A phone clip stored landscape with rotation side data, like the Xiaomi files."""
    add_file(manifest, file_id, "phone", minutes=minutes)
    source = manifest.files[file_id]
    source.width, source.height, source.rotation = 1920, 1080, -90
    assert source.is_vertical


def test_a_vertical_candidate_is_excluded_by_policy_not_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vertical-excluded scenario in specs/clip-selection.

    Selecting a clip the export strategy cannot cut would leave a hole in the edit,
    and dropping it silently is the kind of thing that is only found in CapCut.
    """
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    vertical_file(manifest, "v")
    add_segment(manifest, "v:0", "v", 0.99)
    add_file(manifest, "d", "drone", minutes=30)
    add_segment(manifest, "d:0", "d", 0.40)

    config = open_config()
    config.export.vertical_strategy = "exclude"
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["d:0"]
    excluded = manifest.segments["v:0"]
    assert excluded.outcome == "candidate"
    assert excluded.reason == "vertical"
    assert excluded.order is None


def test_another_vertical_strategy_lets_the_clip_compete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    vertical_file(manifest, "v")
    add_segment(manifest, "v:0", "v", 0.99)

    config = open_config()
    config.export.vertical_strategy = "blur_pad"
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["v:0"]
    assert manifest.segments["v:0"].reason is None


def test_the_exclusion_is_cleared_when_the_strategy_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mark says what the current strategy does, so a re-run has to re-decide it."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    vertical_file(manifest, "v")
    add_segment(manifest, "v:0", "v", 0.99)

    config = open_config()
    config.export.vertical_strategy = "exclude"
    select_clips(manifest, config)
    assert manifest.segments["v:0"].reason == "vertical"

    config.export.vertical_strategy = "center_crop"
    select_clips(manifest, config)
    assert manifest.segments["v:0"].reason is None
    assert manifest.segments["v:0"].outcome == "selected"


def test_a_rejection_reason_survives_the_exclusion_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only policy marks are disposable; a quality rejection is not."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    vertical_file(manifest, "v")
    add_segment(manifest, "v:0", "v", 0.1, outcome="rejected", reason="shaky")

    config = open_config()
    config.export.vertical_strategy = "exclude"
    select_clips(manifest, config)

    assert manifest.segments["v:0"].outcome == "rejected"
    assert manifest.segments["v:0"].reason == "shaky"


def test_a_horizontal_clip_is_never_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "p", "phone")
    add_segment(manifest, "p:0", "p", 0.9)

    config = open_config()
    config.export.vertical_strategy = "exclude"
    select_clips(manifest, config)

    assert selected_ids(manifest) == ["p:0"]
    assert manifest.segments["p:0"].reason is None


def gps_file(
    manifest: Manifest,
    file_id: str,
    minutes: float,
    metres_north: float = 0.0,
    source_class: str = "drone",
) -> None:
    """A file at a known offset from one bay, so places are exact rather than plausible."""
    add_file(
        manifest,
        file_id,
        source_class,
        minutes=minutes,
        gps=(39.9664 + metres_north / 111_320.0, 9.6850),
    )


def test_five_shots_one_visit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scenario in specs/clip-selection, and the CapCut complaint that started it.

    Five drone files at one spot inside eleven minutes. The visual hash split them
    across clusters, so only a cap that asks where they were shot holds them back.
    """
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(5):
        gps_file(manifest, f"n{index}", minutes=index * 2.0, metres_north=index * 20.0)
        add_segment(manifest, f"n{index}:0", f"n{index}", 0.9 - index * 0.01)
    # Somewhere else entirely, so eligible candidates outside the visit remain.
    for index in range(3):
        gps_file(manifest, f"f{index}", minutes=600 + index, metres_north=5000.0)
        add_segment(manifest, f"f{index}:0", f"f{index}", 0.5)

    config = open_config()
    config.selection.max_clips_per_place = 3
    config.selection.max_clips = 6
    select_clips(manifest, config)

    near = [s for s in manifest.segments.values() if s.file_id.startswith("n")]
    chosen = [s for s in near if s.outcome == "selected"]
    held = [s for s in near if s.outcome == "candidate"]
    assert len(chosen) == 3
    assert len(held) == 2
    for segment in held:
        assert segment.reason == "place_cap"
        assert sorted(segment.held_by) == sorted(s.id for s in chosen)


def test_the_place_cap_is_lifted_last(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scenario in specs/clip-selection: an edit short of clips is worse."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(5):
        gps_file(manifest, f"n{index}", minutes=index * 2.0, metres_north=index * 20.0)
        add_segment(manifest, f"n{index}:0", f"n{index}", 0.9 - index * 0.01)

    config = open_config()
    config.selection.max_clips_per_place = 3
    config.selection.max_clips = 5
    result = select_clips(manifest, config)

    assert result.count == 5
    assert result.relaxed_gap


def test_a_candidate_without_gps_is_never_held_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absence of GPS is absence of evidence, not evidence of a different place."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(4):
        add_file(manifest, f"a{index}", "actioncam", minutes=index * 2.0)
        add_segment(manifest, f"a{index}:0", f"a{index}", 0.9)

    config = open_config()
    config.selection.max_clips_per_place = 1
    config.selection.max_clips = 4
    select_clips(manifest, config)

    assert len(selected_ids(manifest)) == 4
    for segment in manifest.segments.values():
        assert segment.place_id is None
        assert segment.visit_id is None
        assert segment.reason is None


def test_two_visits_to_one_place_each_get_their_own_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(3):
        gps_file(manifest, f"m{index}", minutes=index * 2.0)
        add_segment(manifest, f"m{index}:0", f"m{index}", 0.9)
    # The next day, same bay.
    for index in range(3):
        gps_file(manifest, f"t{index}", minutes=24 * 60 + index * 2.0)
        add_segment(manifest, f"t{index}:0", f"t{index}", 0.9)

    config = open_config()
    config.selection.max_clips_per_place = 2
    config.selection.max_clips = 4
    result = select_clips(manifest, config)

    assert result.places == 1
    assert result.visits == 2
    assert result.count == 4
    morning = [s for s in manifest.segments.values() if s.file_id.startswith("m")]
    assert sum(1 for s in morning if s.outcome == "selected") == 2


def test_places_and_visits_are_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    gps_file(manifest, "a", minutes=0.0)
    add_segment(manifest, "a:0", "a", 0.9)
    gps_file(manifest, "b", minutes=30.0, metres_north=4000.0)
    add_segment(manifest, "b:0", "b", 0.8)

    result = select_clips(manifest, open_config())

    assert result.places == 2
    assert result.visits == 2
    assert manifest.selection.places == 2
    assert manifest.selection.visits == 2
    assert manifest.segments["a:0"].place_id != manifest.segments["b:0"].place_id


def test_the_place_mark_is_cleared_between_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mark says what this configuration does, so a looser cap has to undo it."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(4):
        gps_file(manifest, f"n{index}", minutes=index * 2.0)
        add_segment(manifest, f"n{index}:0", f"n{index}", 0.9 - index * 0.01)
    for index in range(2):
        gps_file(manifest, f"f{index}", minutes=600 + index, metres_north=5000.0)
        add_segment(manifest, f"f{index}:0", f"f{index}", 0.5)

    config = open_config()
    config.selection.max_clips_per_place = 2
    config.selection.max_clips = 4
    select_clips(manifest, config)
    assert any(s.reason == "place_cap" for s in manifest.segments.values())

    config.selection.max_clips_per_place = 99
    select_clips(manifest, config)
    assert all(s.reason != "place_cap" for s in manifest.segments.values())
    assert all(not s.held_by for s in manifest.segments.values())


def test_a_rejection_survives_the_place_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    gps_file(manifest, "a", minutes=0.0)
    add_segment(manifest, "a:0", "a", 0.1, outcome="rejected", reason="shaky")
    gps_file(manifest, "b", minutes=2.0)
    add_segment(manifest, "b:0", "b", 0.9)

    select_clips(manifest, open_config())

    assert manifest.segments["a:0"].outcome == "rejected"
    assert manifest.segments["a:0"].reason == "shaky"


# --- candidate share ceiling -------------------------------------------------


def test_the_candidate_share_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scenario in specs/clip-selection: 60 candidates, max_clips 40, share 0.5."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(60):
        add_file(manifest, f"c{index}", "actioncam", minutes=index * 10.0)
        add_segment(manifest, f"c{index}:0", f"c{index}", 0.5)

    config = open_config()
    config.selection.max_candidate_share = 0.5
    config.selection.max_clips = 40
    result = select_clips(manifest, config)

    assert result.max_clips == 30
    assert result.count == 30
    assert result.ceiling_applied


def test_an_explicit_max_clips_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scenario in specs/clip-selection: the flag is the user overruling the ceiling."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(60):
        add_file(manifest, f"c{index}", "actioncam", minutes=index * 10.0)
        add_segment(manifest, f"c{index}:0", f"c{index}", 0.5)

    config = open_config()
    config.selection.max_candidate_share = 0.5
    result = select_clips(manifest, config, SelectionOverrides(max_clips=40))

    assert result.max_clips == 40
    assert result.count == 40
    assert not result.ceiling_applied


def test_the_ceiling_does_not_bind_on_a_large_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(130):
        add_file(manifest, f"c{index}", "actioncam", minutes=index * 10.0)
        add_segment(manifest, f"c{index}:0", f"c{index}", 0.5)

    config = open_config()
    config.selection.max_candidate_share = 0.5
    config.selection.max_clips = 40
    result = select_clips(manifest, config)

    assert result.max_clips == 40
    assert not result.ceiling_applied


def test_the_ceiling_rounds_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(9):
        add_file(manifest, f"c{index}", "actioncam", minutes=index * 10.0)
        add_segment(manifest, f"c{index}:0", f"c{index}", 0.5)

    config = open_config()
    config.selection.max_candidate_share = 0.5
    config.selection.max_clips = 40
    result = select_clips(manifest, config)

    # Half of nine is 4.5, and the ceiling is a bound on slots, not a target.
    assert result.max_clips == 5


def test_clips_held_back_by_policy_do_not_count_towards_the_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A vertical clip cannot be exported, so it is not a slot the edit could use."""
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(10):
        add_file(manifest, f"c{index}", "actioncam", minutes=index * 10.0)
        add_segment(manifest, f"c{index}:0", f"c{index}", 0.5)
    for index in range(10):
        vertical_file(manifest, f"v{index}", minutes=1000 + index * 10.0)
        add_segment(manifest, f"v{index}:0", f"v{index}", 0.5)

    config = open_config()
    config.selection.max_candidate_share = 0.5
    config.selection.max_clips = 40
    config.export.vertical_strategy = "exclude"
    result = select_clips(manifest, config)

    # Ten eligible candidates, not twenty.
    assert result.max_clips == 5


def test_a_lifted_cap_does_not_blame_the_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A visit that went over the cap is one where the cap was lifted, not enforced.

    The candidates that still missed out lost on score like any other, so putting
    `place_cap` on their cards would name the wrong reason.
    """
    no_similarity(monkeypatch)
    manifest = project(tmp_path)
    for index in range(6):
        gps_file(manifest, f"n{index}", minutes=index * 2.0, metres_north=index * 20.0)
        add_segment(manifest, f"n{index}:0", f"n{index}", 0.9 - index * 0.01)

    config = open_config()
    config.selection.max_clips_per_place = 3
    config.selection.max_clips = 5
    result = select_clips(manifest, config)

    assert result.count == 5
    assert result.held_by_place == 0
    for segment in manifest.segments.values():
        assert segment.reason != "place_cap"
        assert not segment.held_by


def tagged_field(tmp_path: Path, beach: int, food: int) -> Manifest:
    """One candidate per file, tagged, scored so the beaches would win on score alone."""
    manifest = project(tmp_path)
    for index in range(beach):
        file_id = f"beach{index}"
        add_file(manifest, file_id, "actioncam", minutes=index * 10)
        segment = add_segment(manifest, f"{file_id}:0", file_id, score=0.9 - index * 0.01)
        segment.tags = [Tag(label="beach", confidence=0.7, source="local", primary=True)]
    for index in range(food):
        file_id = f"food{index}"
        add_file(manifest, file_id, "actioncam", minutes=1000 + index * 10)
        segment = add_segment(manifest, f"{file_id}:0", file_id, score=0.5 - index * 0.01)
        segment.tags = [Tag(label="food", confidence=0.7, source="local", primary=True)]
    return manifest


def tag_settings(max_clips: int, share: float = 0.5) -> AutocutConfig:
    config = AutocutConfig()
    config.selection.max_clips = max_clips
    config.selection.max_share_per_tag = share
    config.selection.max_candidate_share = 0.0
    config.selection.min_temporal_gap_seconds = 0.0
    config.selection.max_clips_per_cluster = 99
    return config


def test_the_tag_share_cap_leaves_room_for_another_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twelve beaches and four plates of food, ten slots.

    Every beach outscores every plate of food, so on score alone the edit would be ten
    beaches. The cap stops at five while food is still available, which is what puts
    all four of them in. The tenth slot is filled by a sixth beach: nothing else is
    eligible by then, and the cap is lifted rather than leaving the edit short.
    """
    no_similarity(monkeypatch)
    manifest = tagged_field(tmp_path, beach=12, food=4)

    result = select_clips(manifest, tag_settings(10))

    dominant = [manifest.segments[i].dominant_tag for i in result.selected]
    assert len(result.selected) == 10
    assert dominant.count("food") == 4
    assert dominant.count("beach") == 6
    assert result.lifted_tag_cap


def test_the_cap_holds_back_candidates_while_another_subject_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = tagged_field(tmp_path, beach=12, food=8)

    result = select_clips(manifest, tag_settings(10))

    dominant = [manifest.segments[i].dominant_tag for i in result.selected]
    assert dominant.count("beach") == 5
    assert dominant.count("food") == 5
    assert not result.lifted_tag_cap
    assert result.held_by_tag == 10


def test_one_tag_everywhere_lifts_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When every candidate carries the same subject the cap cannot help, so it goes."""
    no_similarity(monkeypatch)
    manifest = tagged_field(tmp_path, beach=12, food=0)

    result = select_clips(manifest, tag_settings(10))

    assert len(result.selected) == 10
    assert result.lifted_tag_cap


def test_untagged_candidates_are_never_held_back_by_the_tag_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = tagged_field(tmp_path, beach=12, food=0)
    for index in range(4):
        file_id = f"plain{index}"
        add_file(manifest, file_id, "actioncam", minutes=2000 + index * 10)
        add_segment(manifest, f"{file_id}:0", file_id, score=0.4 - index * 0.01)

    result = select_clips(manifest, tag_settings(10))

    selected = [manifest.segments[segment_id] for segment_id in result.selected]
    # The four untagged clips score below every beach and are taken anyway, because
    # a candidate with no dominant tag is outside the cap entirely.
    assert sum(1 for s in selected if s.dominant_tag is None) == 4
    assert sum(1 for s in selected if s.dominant_tag == "beach") == 6


def test_a_share_of_zero_switches_the_tag_cap_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_similarity(monkeypatch)
    manifest = tagged_field(tmp_path, beach=12, food=4)

    result = select_clips(manifest, tag_settings(10, share=0.0))

    dominant = [manifest.segments[i].dominant_tag for i in result.selected]
    assert dominant.count("beach") == 10
    assert result.held_by_tag == 0


# --- the in-memory entry cache across re-selections (design decision 5, issue #82) --


def test_ten_selections_read_each_cache_entry_from_disk_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autocut.core import cache as cache_module

    no_similarity(monkeypatch)
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_file(manifest, "b")
    add_segment(manifest, "a:0", "a", score=0.9)
    add_segment(manifest, "b:0", "b", score=0.8)

    for key in ("a", "b"):
        cache_module.write_entry(
            cache_module.CacheEntry(
                file_key=key,
                source="original",
                arrays={"timestamps": np.array([0.0, 0.5, 1.0, 1.5])},
                shot_bounds=[(0.0, 2.0)],
            ),
            config,
        )

    calls: list[str] = []
    real_read_entry = cache_module.read_entry

    def counting(file_key: str, cfg: AutocutConfig, sprites: bool = True) -> object:
        calls.append(file_key)
        return real_read_entry(file_key, cfg, sprites=sprites)

    monkeypatch.setattr(cache_module, "read_entry", counting)

    results = [select_clips(manifest, config) for _ in range(10)]

    assert sorted(calls) == ["a", "b"]
    assert all(result.selected == results[0].selected for result in results)

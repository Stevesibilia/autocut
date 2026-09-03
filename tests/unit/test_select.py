"""Selection over synthetic manifests: every scenario in specs/clip-selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile
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
    assert segment.target_duration_s == pytest.approx(3.0)
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

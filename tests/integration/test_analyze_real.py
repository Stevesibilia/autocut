"""Analysis over the real Sardinia footage. Skips unless AUTOCUT_REAL_FOOTAGE is set.

Synthetic fixtures verify mechanics only (ADR 8). Everything here is about whether
the metrics, the segmentation and the rules behave on the material they were written
for, which is the check ADR 8 requires before anything is built on top of them.

Measured on the Linux development host (16 physical cores, ffmpeg 8.0.1, VAAPI
present but ``-hwaccel auto`` picking CUDA and falling back to software) on
2026-09-03, over the 72 video files of the Sardinia set:

    cold run, empty cache   221.5 s wall   (about 3.1 s per file)
    warm run, full cache      6.4 s wall   (about 35x faster, 72 of 72 cache hits)
    cache size               8.1 MB for 72 files
    segments                 77 from 72 files
    analyzed from proxy      43 of 72 (every Action 4 clip)

    rejections               17 of 77 segments
      too_short               6
      shaky                   5   handheld action cam, all five
      low_altitude            4   takeoff spans split out of continuous shots
      no_motion               1   one hovering drone shot at motion 0.0147
      clipped                 1   the blown out night clip

The rejection counts are the ones the m2-scoring-tuning thresholds produce. Before that
change the same footage gave 13 rejections with ``no_motion`` at 3 and neither ``shaky``
nor ``clipped`` firing at all; the reordered rules now name the blown out night clip as
the exposure defect it is, and ``shaky`` fires for the first time.

The four ``low_altitude`` rejections are the four clips that contain a takeoff
(DJI_0741, DJI_0772, DJI_0793, DJI_0801, heights from 0.6 m). None of them is a
separate shot: the content difference across those files peaks at 0.03 to 0.12, so
shot detection sees one span and the telemetry driven split is what isolates the
takeoff. Without it the altitude rule cannot fire on this footage at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autocut.core.analyze import analyze_files
from autocut.core.config import AutocutConfig
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest

pytestmark = [pytest.mark.real_footage, pytest.mark.ffmpeg]


@pytest.fixture(scope="module")
def analyzed(real_footage_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Manifest:
    """One analysis pass over the whole folder, shared by every test in the module."""
    from datetime import UTC, datetime

    workspace = tmp_path_factory.mktemp("real")
    config = AutocutConfig()
    # A cache of its own, so the test neither reads nor pollutes the developer's.
    config.cache.dir = workspace / "cache"
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now,
        updated_at=now,
        sources=[real_footage_dir],
        output_dir=workspace / "edit",
    )
    manifest.files = {source.id: source for source in ingest([real_footage_dir], config)}
    analyze_files(manifest, config, lambda event: None)
    return manifest


def segments_of(manifest: Manifest, predicate: Any) -> list[Any]:
    return [s for s in manifest.segments.values() if predicate(manifest.files[s.file_id])]


def test_every_probed_file_has_at_least_one_scored_segment(analyzed: Manifest) -> None:
    """Includes the 33 ms Action 4 clip, which the fps filter alone yields no frame for."""
    with_segments = {segment.file_id for segment in analyzed.segments.values()}
    assert with_segments == set(analyzed.files)
    for segment in analyzed.segments.values():
        assert segment.score is not None
        assert 0.0 <= segment.score <= 1.0
        assert segment.metrics is not None


def test_every_action4_file_is_analyzed_from_its_proxy(analyzed: Manifest) -> None:
    action = segments_of(analyzed, lambda f: f.source_class == "actioncam")
    assert action
    for segment in action:
        assert segment.analyzed_from == "proxy", analyzed.files[segment.file_id].path.name


def test_files_without_a_proxy_are_analyzed_from_the_original(analyzed: Manifest) -> None:
    originals = segments_of(analyzed, lambda f: f.proxy_path is None)
    assert originals
    assert all(segment.analyzed_from == "original" for segment in originals)


def test_at_least_one_drone_segment_is_rejected_for_low_altitude(analyzed: Manifest) -> None:
    drone = segments_of(analyzed, lambda f: f.source_class == "drone")
    rejected = [segment for segment in drone if segment.reason == "low_altitude"]
    assert rejected, "no takeoff was isolated and rejected on the Sardinia set"
    for segment in rejected:
        assert segment.outcome == "rejected"
        # A takeoff is not a separate shot, so it can only exist as a split span.
        assert segment.split_reason == "altitude"
        assert segment.metrics is not None


def test_a_split_takeoff_leaves_a_usable_cruise_segment(analyzed: Manifest) -> None:
    """Rejecting the takeoff must not cost the flight it belongs to."""
    takeoffs = [
        segment
        for segment in analyzed.segments.values()
        if segment.reason == "low_altitude" and segment.split_reason == "altitude"
    ]
    assert takeoffs
    for takeoff in takeoffs:
        siblings = [
            segment
            for segment in analyzed.segments.values()
            if segment.file_id == takeoff.file_id and segment.id != takeoff.id
        ]
        assert siblings, analyzed.files[takeoff.file_id].path.name
        assert any(segment.outcome == "candidate" for segment in siblings)


def test_files_without_height_telemetry_are_never_split_on_altitude(analyzed: Manifest) -> None:
    without = segments_of(analyzed, lambda f: f.telemetry == "none")
    assert without
    assert all(segment.split_reason is None for segment in without)


def test_rejection_reasons_are_all_known(analyzed: Manifest) -> None:
    from autocut.core.rules import REASONS

    reasons = {segment.reason for segment in analyzed.segments.values() if segment.reason}
    assert reasons
    assert reasons <= set(REASONS)


def test_most_segments_survive_the_rules(analyzed: Manifest) -> None:
    """A pass that rejects most of a real holiday folder is a broken pass."""
    total = len(analyzed.segments)
    rejected = sum(1 for segment in analyzed.segments.values() if segment.outcome == "rejected")
    assert total > 0
    assert rejected / total < 0.5, f"{rejected} of {total} segments rejected"


def test_thumbnails_exist_for_every_segment(analyzed: Manifest) -> None:
    for segment in analyzed.segments.values():
        assert segment.thumbnail is not None
        assert segment.thumbnail.exists()

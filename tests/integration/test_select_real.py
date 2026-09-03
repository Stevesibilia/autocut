"""Selection over the real Sardinia footage. Skips unless AUTOCUT_REAL_FOOTAGE is set.

Synthetic fixtures verify mechanics only (ADR 8), so the questions this module asks
are the ones synthetic clips cannot answer: does the visual signal separate shots of
the same bay from shots of another day, do the caps and the class share leave a set
that looks like an edit, and is selection actually fast enough to be re-run twenty
times over one analysis.

Measured on the Linux development host on 2026-09-03, over the 72 video files of the
Sardinia set with the shipped defaults (`max_clips` 40, `diversity_lambda` 0.6,
`cluster_threshold` 0.75):

    candidates                60 of 77 segments (actioncam 35, drone 21, phone 4)
      held back as vertical   2 phone candidates, under the exclude strategy
      eligible                58
    places and visits         6 and 6, over the 25 candidates that carry GPS
      held back by the cap    6 candidates, 4 in place 2 and 2 in place 3
    selected, defaults        29 (actioncam 19, drone 9, phone 1), the ceiling binding
    selected, --max-clips 40  40 (actioncam 24, drone 14, phone 2)
    clusters                  45 over the 60 candidates
      sizes                   36 singletons, 7 pairs, one of 3, one of 7
    total duration            77.0 s with defaults, 111.1 s at 40 clips
    wall time                 0.46 s in process, 0.95 s through the CLI

    selection changes         lambda 0.0 to 0.6   4 of 40 clips differ
                              lambda 0.6 to 1.0   2 of 40 clips differ
                              lambda 0.0 to 1.0   2 of 40 clips differ

Two thirds of the candidates fit inside `max_clips` on this set, so lambda moves a
handful of clips rather than reshaping the edit. That is a property of the footage
and the caps, not of the penalty. The same three runs with `--max-clips 15` change
6, 4 and 10 clips of 15, which is the control the GUI slider is meant to be. The
numbers above are what the defaults do on this footage today, not a target to
preserve.

The class counts moved when export gained its vertical strategy: three of the five
phone files are display-vertical, so two of their candidates are held back and the
drone and action cam take the freed slots. The durations are per clip since
m3-durations, so the edit no longer runs to a round 120 s.

Since m3-place-cap the default run is 29 clips rather than 40, because the candidate
share ceiling binds at half of the 58 eligible candidates before `max_clips` does.
That is one clip under the 30 to 50 band in SPEC.md section 1, and the band describes
a folder of about 150 raw files where the ceiling would allow 65 and `max_clips` would
bind first. `--max-clips 40` still reaches the band on this set.
"""

from __future__ import annotations

import collections
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.analyze import analyze_files
from autocut.core.config import AutocutConfig
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest
from autocut.core.select import SelectionOverrides, select_clips

pytestmark = [pytest.mark.real_footage, pytest.mark.ffmpeg]


@pytest.fixture(scope="module")
def project(
    real_footage_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Manifest, AutocutConfig]:
    """One analysis pass over the whole folder, then every test selects from it."""
    workspace = tmp_path_factory.mktemp("real-select")
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
    return manifest, config


def classes_of(manifest: Manifest, outcome: str) -> collections.Counter[str]:
    return collections.Counter(
        manifest.files[segment.file_id].source_class
        for segment in manifest.segments.values()
        if segment.outcome == outcome
    )


def test_the_candidate_share_ceiling_binds_on_this_folder(
    project: tuple[Manifest, AutocutConfig],
) -> None:
    """This set is half the size the success criterion in SPEC.md section 1 describes.

    That criterion is 30 to 50 clips from about 150 raw files. Sardinia is 72 files
    and 60 candidates, 58 of them eligible once the vertical phone clips are held
    back, so the candidate share ceiling binds at 29 slots before `max_clips` of 40
    ever does. Twenty-nine is one short of the criterion's floor, and deliberately:
    forty slots for sixty candidates is a rejection list rather than a selection.
    The floor applies to a folder twice this size, where 130 candidates give 65 slots
    and `max_clips` binds first.
    """
    manifest, config = project
    result = select_clips(manifest, config)
    # Eligibility as the ceiling sees it, before the run marks anything: the vertical
    # exclusion is decided up front, while `place_cap` is an outcome of selection and
    # counting it here would measure the answer against itself.
    eligible = sum(
        1
        for segment in manifest.segments.values()
        if segment.outcome in ("candidate", "selected") and segment.reason != "vertical"
    )
    assert result.ceiling_applied
    assert result.count == result.max_clips
    assert result.max_clips == math.ceil(config.selection.max_candidate_share * eligible)
    assert result.max_clips < config.selection.max_clips


def test_an_explicit_max_clips_reaches_the_success_criterion(
    project: tuple[Manifest, AutocutConfig],
) -> None:
    """The 30 to 50 band of SPEC.md section 1, which the flag still reaches here."""
    manifest, config = project
    result = select_clips(manifest, config, SelectionOverrides(max_clips=40))
    assert not result.ceiling_applied
    assert result.count == 40
    assert 30 <= result.count <= 50


def test_every_class_present_in_the_footage_reaches_the_edit(
    project: tuple[Manifest, AutocutConfig],
) -> None:
    """A holiday shot on three devices must not come back as one device."""
    manifest, config = project
    select_clips(manifest, config)
    candidates = set(classes_of(manifest, "candidate")) | set(classes_of(manifest, "selected"))
    selected = classes_of(manifest, "selected")
    assert set(selected) == candidates, f"{selected} from {candidates}"


def test_no_source_file_exceeds_its_per_file_cap(
    project: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, config = project
    select_clips(manifest, config)
    per_file = collections.Counter(
        segment.file_id for segment in manifest.segments.values() if segment.outcome == "selected"
    )
    for file_id, count in per_file.items():
        cap = config.selection.max_clips_per_file.get(manifest.files[file_id].source_class)
        assert count <= cap, manifest.files[file_id].path.name


def test_the_order_is_a_contiguous_chronology(project: tuple[Manifest, AutocutConfig]) -> None:
    manifest, config = project
    result = select_clips(manifest, config)
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    orders = sorted(segment.order for segment in selected if segment.order is not None)
    assert orders == list(range(1, result.count + 1))


def test_every_candidate_carries_a_window_and_a_cluster(
    project: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, config = project
    select_clips(manifest, config)
    for segment in manifest.segments.values():
        if segment.outcome == "rejected":
            continue
        assert segment.best_center_s is not None, segment.id
        assert segment.target_duration_s, segment.id
        assert segment.cluster_id is not None, segment.id
        start, stop = segment.start_s, segment.end_s
        half = segment.target_duration_s / 2.0
        assert start - 1e-6 <= segment.best_center_s - half, segment.id
        assert segment.best_center_s + half <= stop + 1e-6, segment.id


def test_similarity_finds_near_duplicates_without_flattening_the_folder(
    project: tuple[Manifest, AutocutConfig],
) -> None:
    """The classic signals have to separate the same bay from another day (SPEC 7.4)."""
    manifest, config = project
    result = select_clips(manifest, config)
    assert result.clusters > 1
    sizes = collections.Counter(
        collections.Counter(
            segment.cluster_id
            for segment in manifest.segments.values()
            if segment.cluster_id is not None
        ).values()
    )
    # Some clip must group with another, or the visual signal is measuring nothing.
    assert sum(count for size, count in sizes.items() if size > 1) > 0
    # And most must not, or every beach in the folder is one duplicate.
    assert sizes[1] > result.clusters / 2


def test_turning_the_diversity_slider_changes_the_set(
    project: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, config = project
    picks = {}
    for lam in (0.0, 1.0):
        result = select_clips(manifest, config, SelectionOverrides(diversity_lambda=lam))
        picks[lam] = set(result.selected)
    assert picks[0.0] != picks[1.0]


def test_selection_is_fast_enough_to_re_run(project: tuple[Manifest, AutocutConfig]) -> None:
    """The tuning loop is select twenty times over one analyze, so seconds matter."""
    import time

    manifest, config = project
    start = time.perf_counter()
    select_clips(manifest, config)
    assert time.perf_counter() - start < 5.0


def test_rejections_survive_every_re_run(project: tuple[Manifest, AutocutConfig]) -> None:
    manifest, config = project
    select_clips(manifest, config)
    rejected = {
        segment.id: segment.reason
        for segment in manifest.segments.values()
        if segment.outcome == "rejected"
    }
    assert rejected
    for lam in (0.0, 0.6, 1.0):
        select_clips(manifest, config, SelectionOverrides(diversity_lambda=lam))
        still = {
            segment.id: segment.reason
            for segment in manifest.segments.values()
            if segment.outcome == "rejected"
        }
        assert still == rejected, lam

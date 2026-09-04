"""The real text tower against the synthetic fixtures.

Marked ``ai``, so it runs in the ``dev-ai`` container and nowhere else. What a mocked
encoder cannot say is whether the shipped groups, their null prompts and the logit scale
behave sensibly on a picture that is none of the labels: a colour bar chart is not a
beach, a mountain or a plate of food, and the tagger has to answer with silence rather
than with whichever label is least wrong.

One rule for the assertions here. A probability sitting near a threshold is not a stable
thing to assert on: these are float reductions over 512 dimensions and the last digits
differ between CPUs, so a fixture whose best label is within a few thousandths of its
null prompt lands on either side depending on the runner. Assertions therefore either sit
on a measured margin wide enough to survive that, with the margin written down, or they
allow both outcomes and check the invariant instead. The margins below were measured in
``dev-ai`` on 2026-09-04.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.analyze import analyze_files
from autocut.core.cache import read_entry
from autocut.core.config import AutocutConfig, TagGroup, TagLabel
from autocut.core.embeddings import embed_project
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest
from autocut.core.tags import tag_project

pytestmark = [pytest.mark.ai, pytest.mark.ffmpeg]

# smptebars, a colour bar test card, is the fixture that resembles no label.
BARS = "static.mp4"
MULTISHOT = "multishot.mp4"


def tagged_project(
    synthetic_dir: Path, tmp_path: Path, names: list[str], config: AutocutConfig | None = None
) -> tuple[Manifest, AutocutConfig]:
    settings = config or AutocutConfig()
    settings.cache.dir = tmp_path / "cache"
    # The model directory is left at the platform default on purpose: in dev-ai that
    # is the named volume, so the checkpoint is downloaded once for the whole suite
    # rather than once per test into the container tmpfs.
    sources = [synthetic_dir / name for name in names]

    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=sources, output_dir=tmp_path / "edit"
    )
    manifest.files = {source.id: source for source in ingest(sources, settings)}
    analyze_files(manifest, settings, lambda event: None)
    embedded = embed_project(manifest, settings)
    assert not embedded.skipped, embedded.skipped_reason

    result = tag_project(manifest, settings)
    assert not result.skipped, result.skipped_reason
    return manifest, settings


def test_a_colour_bar_chart_reaches_no_label(synthetic_dir: Path, tmp_path: Path) -> None:
    """The null prompt and the scale have to mean something together.

    Margin: the best subject label is ``people`` at 0.145, which is 0.055 under the
    threshold and 0.086 under the null prompt. Two independent reasons to reject, either
    of which would do on its own.
    """
    manifest, _ = tagged_project(synthetic_dir, tmp_path, [BARS])
    segment = next(iter(manifest.segments.values()))

    assert segment.dominant_tag is None, [
        (tag.label, round(tag.confidence, 3)) for tag in segment.tags
    ]


def test_the_same_shot_can_be_a_subject_and_a_view(synthetic_dir: Path, tmp_path: Path) -> None:
    """Groups must not compete: a label from one never suppresses a label from another.

    Margin: on ``static`` the subject label beats its null by 0.482 and clears the
    threshold by 0.297, and the view label by 0.542 and 0.371. This test deliberately
    uses that one fixture: on ``multishot`` shot 2 the same view label clears the
    threshold by 0.001, which is exactly the kind of number not to assert on.
    """
    config = AutocutConfig()
    config.tags.groups = [
        TagGroup(
            name="subject",
            null_prompt="a photo",
            primary=True,
            labels=[TagLabel(label="colour bars"), TagLabel(label="beach")],
        ),
        TagGroup(
            name="view",
            null_prompt="a photo of something else",
            labels=[TagLabel(label="a television test card")],
        ),
    ]
    config.tags.threshold = 0.4
    manifest, _ = tagged_project(synthetic_dir, tmp_path, [BARS], config)
    segment = next(iter(manifest.segments.values()))

    groups = {tag.group for tag in segment.tags}
    assert groups == {"subject", "view"}, [(t.label, t.group) for t in segment.tags]
    assert segment.dominant_tag == "colour bars"
    assert [tag.label for tag in segment.secondary_tags] == ["a television test card"]


def test_every_tag_carries_its_provenance_and_a_probability(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    manifest, config = tagged_project(synthetic_dir, tmp_path, [BARS, MULTISHOT])

    for segment in manifest.segments.values():
        for tag in segment.tags:
            assert tag.source == "local"
            assert tag.group in {group.name for group in config.tags.groups}
            assert config.tags.threshold <= tag.confidence <= 1.0
        assert len(segment.tags) <= config.tags.max_per_segment
        # The dominant tag leads the list, whatever the confidences are.
        if segment.dominant_tag is not None:
            assert segment.tags[0].label == segment.dominant_tag
            assert segment.tags[0].primary


def test_re_tagging_with_another_label_set_costs_no_embedding(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    """Editing the label list has to be an interactive loop, not a re-analysis.

    The vectors on disk before and after are compared directly, which is the claim in
    the test's name. What the new labels come out as is checked only for the segments
    that got one: on ``multishot`` shot 2 the best label loses to its null prompt by
    0.098 here and by a hair the other way on some runners, so whether that shot ends up
    tagged is not the property under test.
    """
    manifest, settings = tagged_project(synthetic_dir, tmp_path, [MULTISHOT])
    file_id = next(iter(manifest.files))
    before = read_entry(file_id, settings)
    assert before is not None and before.embeddings is not None
    vectors = before.embeddings.copy()

    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    config.tags.groups = [
        TagGroup(
            name="subject",
            null_prompt="a photo of nothing in particular",
            primary=True,
            labels=[TagLabel(label="colour bars"), TagLabel(label="beach")],
        )
    ]
    config.tags.threshold = 0.0

    result = tag_project(manifest, config)

    assert not result.skipped
    assert result.labels == 2
    assert result.groups == 1

    # Nothing was embedded again: the arrays on disk are the ones from before, and a
    # fresh embedding pass finds every file already done.
    after = read_entry(file_id, config)
    assert after is not None and after.embeddings is not None
    assert np.array_equal(after.embeddings, vectors)
    assert embed_project(manifest, config).files_embedded == 0

    # Whatever was tagged was tagged from the new set, and only from it.
    named = {segment.dominant_tag for segment in manifest.segments.values()} - {None}
    assert named, "the new label set tagged nothing at all"
    assert named <= {"colour bars", "beach"}
    assert {tag.group for segment in manifest.segments.values() for tag in segment.tags} == {
        "subject"
    }

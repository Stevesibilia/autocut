"""The real text tower against the synthetic fixtures.

Marked ``ai``, so it runs in the ``dev-ai`` container and nowhere else. What a mocked
encoder cannot say is whether the shipped groups, their null prompts and the logit scale
behave sensibly on a picture that is none of the labels: a colour bar chart is not a
beach, a mountain or a plate of food, and the tagger has to answer with silence rather
than with whichever label is least wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.analyze import analyze_files
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
    """The null prompt and the scale have to mean something together."""
    manifest, _ = tagged_project(synthetic_dir, tmp_path, [BARS])
    segment = next(iter(manifest.segments.values()))

    assert segment.dominant_tag is None, [
        (tag.label, round(tag.confidence, 3)) for tag in segment.tags
    ]


def test_the_same_shot_can_be_a_subject_and_a_view(synthetic_dir: Path, tmp_path: Path) -> None:
    """Groups must not compete: a label from one never suppresses a label from another."""
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
    """Editing the label list has to be an interactive loop, not a re-analysis."""
    manifest, _ = tagged_project(synthetic_dir, tmp_path, [MULTISHOT])
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
    assert {segment.dominant_tag for segment in manifest.segments.values()} <= {
        "colour bars",
        "beach",
    }

"""Descriptions: validation, the correction retry, the cache, the scope and the abort."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.cache import CacheEntry, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.describe import (
    CORRECTION,
    DescribeResult,
    apply_description,
    cache_path,
    describe_project,
    description_key,
    segments_in_scope,
    thumbnail_bytes,
    validate,
)
from autocut.core.events import ProgressEvent
from autocut.core.manifest import Manifest, Metrics, Segment, Tag
from autocut.core.providers import Description, ProviderError

JPEG = b"\xff\xd8\xff\xe0 thumbnail \xff\xd9"


class FakeProvider:
    """Replays answers in order, remembering what it was asked."""

    def __init__(self, answers: list[Description | ProviderError]) -> None:
        self.model = "fake/vision"
        self.answers = answers
        self.calls: list[tuple[bytes, list[str], str | None]] = []

    def describe_frame(
        self, jpeg: bytes, labels: list[str], correction: str | None = None
    ) -> Description | ProviderError:
        self.calls.append((jpeg, labels, correction))
        if not self.answers:
            raise AssertionError("the describe step asked for more answers than were queued")
        return self.answers.pop(0)


def good(
    tags: list[str] | None = None, caption: str = "two people snorkeling", aesthetic: int = 7
) -> Description:
    return Description(
        tags=tags if tags is not None else ["beach", "snorkeling"],
        caption=caption,
        aesthetic=aesthetic,
        model="fake/vision",
        cost_usd=0.0006,
    )


def config_in(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    return config


def project_in(tmp_path: Path, count: int = 2, thumbnails: bool = True) -> Manifest:
    """A manifest whose segments have an embedding reference and a thumbnail on disk."""
    config = config_in(tmp_path)
    write_entry(
        CacheEntry(
            file_key="aaa",
            source="original",
            arrays={"timestamps": np.arange(count, dtype=np.float64)},
            shot_bounds=[(float(i), float(i) + 1.0) for i in range(count)],
            thumb_frames=np.zeros((count, 8, 8, 3), dtype=np.uint8),
        ),
        config,
    )
    thumbs = tmp_path / "edit" / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "edit"
    )
    for index in range(count):
        segment_id = f"aaa:{index}"
        thumbnail = thumbs / f"aaa_{index}.jpg"
        if thumbnails:
            thumbnail.write_bytes(JPEG)
        manifest.segments[segment_id] = Segment(
            id=segment_id,
            file_id="aaa",
            start_s=float(index),
            end_s=float(index) + 1.0,
            embedding_ref=f"aaa:{index}",
            thumbnail=thumbnail if thumbnails else None,
            metrics=Metrics(
                sharpness=100.0,
                exposure_clipped=0.0,
                motion=0.3,
                stability=0.9,
                colorfulness=0.2,
            ),
        )
    return manifest


def test_a_valid_answer_lands_on_the_segment(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=1)
    provider = FakeProvider([good()])

    result = describe_project(manifest, config_in(tmp_path), provider)

    segment = manifest.segments["aaa:0"]
    assert result.described == 1
    assert result.requests == 1
    assert result.cost_usd == pytest.approx(0.0006)
    assert [tag.label for tag in segment.tags] == ["beach", "snorkeling"]
    assert all(tag.source == "cloud" and tag.confidence == 1.0 for tag in segment.tags)
    assert segment.caption == "two people snorkeling"
    assert segment.metrics is not None
    assert segment.metrics.aesthetic == pytest.approx(0.7)
    assert segment.description_error is None


def test_the_dominant_tag_is_the_first_cloud_tag(tmp_path: Path) -> None:
    """The scenario from the spec: local beach 0.62 against cloud snorkeling, beach."""
    manifest = project_in(tmp_path, count=1)
    segment = manifest.segments["aaa:0"]
    segment.tags = [
        Tag(label="beach", confidence=0.62, source="local", group="subject", primary=True)
    ]

    describe_project(
        manifest, config_in(tmp_path), FakeProvider([good(tags=["snorkeling", "beach"])])
    )

    assert segment.dominant_tag == "snorkeling"
    # The local tag is still there, with its own confidence and source.
    local = [tag for tag in segment.tags if tag.source == "local"]
    assert [(tag.label, tag.confidence) for tag in local] == [("beach", 0.62)]


def test_an_invalid_answer_earns_one_correction(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=1)
    prose = Description(model="fake/vision", cost_usd=0.0002, raw="I cannot")
    provider = FakeProvider([prose, good()])

    result = describe_project(manifest, config_in(tmp_path), provider)

    assert result.described == 1
    assert result.requests == 2
    assert [call[2] for call in provider.calls] == [None, CORRECTION]
    assert manifest.segments["aaa:0"].caption == "two people snorkeling"


def test_prose_twice_is_a_failure_and_the_run_continues(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=2)
    prose = Description(model="fake/vision", cost_usd=0.0002, raw="I cannot")
    provider = FakeProvider([prose, prose, good()])

    result = describe_project(manifest, config_in(tmp_path), provider)

    assert result.failed == 1
    assert result.described == 1
    assert manifest.segments["aaa:0"].description_error is not None
    assert "invalid answer twice" in manifest.segments["aaa:0"].description_error
    assert manifest.segments["aaa:1"].caption == "two people snorkeling"


def test_a_second_run_makes_no_request(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_in(tmp_path, count=2)
    describe_project(manifest, config, FakeProvider([good(), good()]))

    empty = FakeProvider([])
    result = describe_project(manifest, config, empty)

    assert empty.calls == []
    assert result.requests == 0
    assert result.from_cache == 2
    assert result.described == 2
    assert result.cost_usd == 0.0


def test_a_new_prompt_version_invalidates_the_cache(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_in(tmp_path, count=1)
    describe_project(manifest, config, FakeProvider([good()]))

    config.providers.prompt_version = 2
    provider = FakeProvider([good()])
    result = describe_project(manifest, config, provider)

    assert len(provider.calls) == 1
    assert result.requests == 1


def test_a_new_model_invalidates_the_cache(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_in(tmp_path, count=1)
    describe_project(manifest, config, FakeProvider([good()]))

    config.providers.vision_model = "openai/gpt-5-mini"
    provider = FakeProvider([good()])
    describe_project(manifest, config, provider)

    assert len(provider.calls) == 1


def test_the_cache_is_keyed_on_the_embedding_reference(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_in(tmp_path, count=1)
    describe_project(manifest, config, FakeProvider([good()]))

    path = cache_path(config, "aaa:0")
    assert path.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["caption"] == "two people snorkeling"
    assert stored["aesthetic"] == 7
    # The raw answer is not kept: it is not needed again and it is the largest field.
    assert "raw" not in stored


def test_a_segment_without_an_embedding_falls_back_to_its_id(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=1)
    manifest.segments["aaa:0"].embedding_ref = None

    assert description_key(manifest.segments["aaa:0"]) == "aaa:0"


def test_the_scope_selected_describes_only_the_selection(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    config.providers.describe_scope = "selected"
    manifest = project_in(tmp_path, count=3)
    manifest.segments["aaa:1"].outcome = "selected"
    manifest.segments["aaa:1"].order = 1
    provider = FakeProvider([good()])

    result = describe_project(manifest, config, provider)

    assert result.in_scope == 1
    assert len(provider.calls) == 1
    assert manifest.segments["aaa:0"].caption is None
    assert manifest.segments["aaa:1"].caption == "two people snorkeling"


def test_the_scope_candidates_includes_the_selection(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=2)
    manifest.segments["aaa:1"].outcome = "selected"

    assert [s.id for s in segments_in_scope(manifest, "candidates")] == ["aaa:0", "aaa:1"]


def test_a_rejected_segment_is_never_described(tmp_path: Path) -> None:
    """Paying to caption a clip the rules already threw away is money for nothing."""
    manifest = project_in(tmp_path, count=2)
    manifest.segments["aaa:1"].outcome = "rejected"
    manifest.segments["aaa:1"].reason = "shaky"

    assert [s.id for s in segments_in_scope(manifest, "candidates")] == ["aaa:0"]


def test_repeated_failures_stop_the_step(tmp_path: Path) -> None:
    """A persistent outage costs about max_failures requests, not one per segment."""
    config = config_in(tmp_path)
    config.providers.max_failures = 2
    config.providers.max_concurrency = 1
    manifest = project_in(tmp_path, count=6)
    outage = ProviderError(message="provider returned 503", retryable=True, status=503)
    provider = FakeProvider([outage] * 6)

    result = describe_project(manifest, config, provider)

    assert result.aborted
    assert len(provider.calls) == 2
    assert result.requests == 2
    # Every segment says why it has no description, including the ones never attempted.
    assert all(s.description_error for s in manifest.segments.values())
    assert result.failed == 6


def test_one_success_resets_the_failure_run(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    config.providers.max_failures = 2
    config.providers.max_concurrency = 1
    manifest = project_in(tmp_path, count=4)
    outage = ProviderError(message="503", retryable=True, status=503)
    provider = FakeProvider([outage, good(), outage, good()])

    result = describe_project(manifest, config, provider)

    assert not result.aborted
    assert result.described == 2
    assert result.failed == 2


def test_the_cost_of_every_answer_is_summed(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=3)
    answers = [good(), good(), good()]
    for index, answer in enumerate(answers):
        answer.cost_usd = 0.001 * (index + 1)

    result = describe_project(manifest, config_in(tmp_path), FakeProvider(answers))

    assert result.cost_usd == pytest.approx(0.006)


def test_progress_reports_one_event_per_segment(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=2)
    events: list[ProgressEvent] = []

    describe_project(manifest, config_in(tmp_path), FakeProvider([good(), good()]), events.append)

    assert [event.current for event in events] == [1, 2]
    assert {event.stage for event in events} == {"describe"}
    assert {event.total for event in events} == {2}


def test_the_configured_labels_are_offered_to_the_model(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=1)
    provider = FakeProvider([good()])

    describe_project(manifest, config_in(tmp_path), provider)

    offered = provider.calls[0][1]
    assert "beach" in offered
    assert "aerial" in offered
    assert "sunset" in offered


def test_a_segment_with_no_thumbnail_on_disk_is_encoded_from_the_cache(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_in(tmp_path, count=1, thumbnails=False)

    jpeg = thumbnail_bytes(manifest.segments["aaa:0"], config)

    assert jpeg is not None
    assert jpeg.startswith(b"\xff\xd8")


def test_a_written_thumbnail_is_sent_as_it_is(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_in(tmp_path, count=1)

    assert thumbnail_bytes(manifest.segments["aaa:0"], config) == JPEG


def test_a_segment_with_no_frame_anywhere_fails_without_a_request(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "edit"
    )
    manifest.segments["zzz:0"] = Segment(id="zzz:0", file_id="zzz", start_s=0.0, end_s=1.0)
    provider = FakeProvider([])

    result = describe_project(manifest, config, provider)

    assert provider.calls == []
    assert result.failed == 1
    assert manifest.segments["zzz:0"].description_error == "no thumbnail to describe"


def test_no_provider_is_a_skip_rather_than_a_crash(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=1)

    result = describe_project(manifest, config_in(tmp_path), None)

    assert result.skipped
    assert result.described == 0


def test_an_empty_project_describes_nothing(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "edit"
    )

    result = describe_project(manifest, config_in(tmp_path), FakeProvider([]))

    assert result.in_scope == 0
    assert not result.skipped


def test_validation_trims_a_long_caption_rather_than_rejecting_it() -> None:
    long = " ".join(f"word{index}" for index in range(30))
    validated, reason = validate(Description(caption=long, aesthetic=7))

    assert reason is None
    assert validated.caption is not None
    assert len(validated.caption.split()) == 20


def test_validation_clamps_an_aesthetic_out_of_range() -> None:
    high, _ = validate(Description(caption="x", aesthetic=11))
    low, _ = validate(Description(caption="x", aesthetic=-4))

    assert high.aesthetic == 10
    assert low.aesthetic == 1


def test_validation_keeps_at_most_five_tags() -> None:
    validated, reason = validate(Description(tags=[f"t{index}" for index in range(9)]))

    assert reason is None
    assert len(validated.tags) == 5


def test_validation_lowercases_and_strips() -> None:
    validated, _ = validate(Description(tags=["  Beach ", ""], caption="  A Beach.  "))

    assert validated.tags == ["beach"]
    assert validated.caption == "a beach"


def test_validation_rejects_an_answer_with_none_of_the_fields() -> None:
    _, reason = validate(Description(raw="{}", tags=[], caption=None, aesthetic=None))

    assert reason is not None


def test_applying_a_description_twice_does_not_pile_up_cloud_tags(tmp_path: Path) -> None:
    manifest = project_in(tmp_path, count=1)
    segment = manifest.segments["aaa:0"]

    apply_description(segment, good(tags=["beach"]))
    apply_description(segment, good(tags=["food"]))

    assert [tag.label for tag in segment.tags] == ["food"]


def test_an_empty_result_reports_no_model() -> None:
    assert DescribeResult().model == "none"
    assert not DescribeResult().skipped

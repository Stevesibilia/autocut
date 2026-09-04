"""Zero-shot tagging: grouped softmaxes, null prompts, the threshold and provenance.

The text tower is mocked throughout. Prompt vectors are an orthonormal basis, so a
segment vector's coordinates are its cosines against the prompts and the expected
probability can be written down independently of the implementation.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.cache import CacheEntry, write_entry
from autocut.core.config import AutocutConfig, TagGroup, TagLabel
from autocut.core.events import ProgressEvent
from autocut.core.manifest import Manifest, Segment, Tag
from autocut.core.tags import (
    EncodedGroup,
    TagResult,
    encode_groups,
    group_prompts,
    prompt_for,
    tag_embeddings,
    tag_project,
)

SCALE = 10.0

SUBJECT = TagGroup(
    name="subject",
    null_prompt="a photo",
    primary=True,
    labels=[TagLabel(label="beach"), TagLabel(label="food")],
)
VIEW = TagGroup(
    name="view",
    null_prompt="a photo taken at ground level",
    labels=[TagLabel(label="aerial", prompt="an aerial photo taken from a drone")],
)
GROUPS = [SUBJECT, VIEW]

# Prompt rows, in the order encode_groups asks for them: beach, food, subject null,
# aerial, view null.
BEACH, FOOD, SUBJECT_NULL, AERIAL, VIEW_NULL = range(5)
WIDTH = 5


def basis(count: int = WIDTH) -> np.ndarray:
    return np.eye(count, dtype=np.float32)


class FakeTextEncoder:
    """Encodes prompts to the basis in the order they are asked for."""

    def __init__(self, count: int = WIDTH) -> None:
        self.count = count
        self.prompts: list[str] = []

    def __call__(self, prompts: list[str]) -> np.ndarray:
        self.prompts.extend(prompts)
        return basis(self.count)[: len(prompts)]


def vector(**weights: float) -> np.ndarray:
    """A unit vector with the given cosine against each named prompt row."""
    row = np.zeros(WIDTH, dtype=np.float32)
    for index, value in weights.items():
        row[int(index)] = value
    norm = float(np.linalg.norm(row))
    return row / norm if norm else row


def leaning(target: int, against: int, probability: float) -> np.ndarray:
    """A vector whose softmax over two live rows gives ``probability`` to ``target``.

    The view group is pushed onto its null prompt, because an orthonormal test basis
    otherwise leaves ``aerial`` and its null tied at a cosine of zero and splitting that
    group's probability evenly. Real embeddings do not tie, and a test that reads as
    "no tags" must not depend on which side of a tie the threshold falls.
    """
    gap = math.log(probability / (1.0 - probability)) / SCALE
    second = (-gap + math.sqrt(2.0 - gap**2)) / 2.0
    row = np.zeros(WIDTH, dtype=np.float32)
    row[target], row[against] = second + gap, second
    if VIEW_NULL not in (target, against) and AERIAL not in (target, against):
        row[VIEW_NULL] = 0.5
    return row


def encoded() -> list[EncodedGroup]:
    return encode_groups(GROUPS, FakeTextEncoder())


def config_in(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    config.tags.groups = list(GROUPS)
    config.tags.logit_scale = SCALE
    return config


def project_with(tmp_path: Path, vectors: np.ndarray, count: int | None = None) -> Manifest:
    """A manifest whose one file has ``vectors`` in its cache entry, one per segment."""
    config = config_in(tmp_path)
    rows = int(vectors.shape[0])
    write_entry(
        CacheEntry(
            file_key="aaa",
            source="original",
            arrays={"timestamps": np.arange(rows, dtype=np.float64)},
            shot_bounds=[(float(i), float(i) + 1.0) for i in range(rows)],
            thumb_frames=np.zeros((rows, 4, 4, 3), dtype=np.uint8),
            embeddings=vectors.astype(np.float32),
            embedding_model=config.providers.embedding_model,
        ),
        config,
    )
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "out"
    )
    for index in range(count if count is not None else rows):
        segment_id = f"aaa:{index}"
        manifest.segments[segment_id] = Segment(
            id=segment_id, file_id="aaa", start_s=float(index), end_s=float(index) + 1.0
        )
    return manifest


def test_a_group_encodes_its_labels_and_then_its_null_prompt() -> None:
    assert group_prompts(SUBJECT) == ["a photo of beach", "a photo of food", "a photo"]
    assert group_prompts(VIEW) == [
        "an aerial photo taken from a drone",
        "a photo taken at ground level",
    ]


def test_encoding_splits_the_rows_back_into_their_groups() -> None:
    encoder = FakeTextEncoder()
    groups = encode_groups(GROUPS, encoder)

    assert encoder.prompts == group_prompts(SUBJECT) + group_prompts(VIEW)
    assert [entry.group.name for entry in groups] == ["subject", "view"]
    # Two labels plus a null prompt, then one label plus a null prompt.
    assert [entry.matrix.shape[0] for entry in groups] == [3, 2]
    assert all(np.allclose(np.linalg.norm(entry.matrix, axis=1), 1.0) for entry in groups)


def test_a_group_without_labels_is_left_out() -> None:
    empty = TagGroup(name="empty", null_prompt="a photo", labels=[])
    assert [e.group.name for e in encode_groups([SUBJECT, empty], FakeTextEncoder())] == ["subject"]


def test_a_beach_shot_takes_the_label_it_is_closest_to() -> None:
    tags = tag_embeddings(leaning(BEACH, SUBJECT_NULL, 0.62)[None, :], encoded(), SCALE, 0.2, 3)[0]

    assert tags[0].label == "beach"
    assert tags[0].confidence == pytest.approx(0.62, abs=0.005)
    assert tags[0].source == "local"
    assert tags[0].group == "subject"
    assert tags[0].primary


def test_the_null_prompt_takes_the_shot_that_is_none_of_the_labels() -> None:
    """The ambiguous case: every group answers with its null prompt, so no tag."""
    tags = tag_embeddings(leaning(SUBJECT_NULL, BEACH, 0.9)[None, :], encoded(), SCALE, 0.2, 3)[0]

    assert tags == []


def test_a_label_has_to_beat_its_own_null_prompt() -> None:
    """A threshold means different things in a group of two rows and one of eight.

    ``view`` here has one label and a null, so the smallest probability a label can take
    is a half of whatever the two share. A threshold of 0.2 accepts that every time, and
    the null prompt is what makes the group able to say no.
    """
    single = TagGroup(
        name="view",
        null_prompt="a photo taken at ground level",
        labels=[TagLabel(label="aerial")],
    )
    encoded_single = encode_groups([single], FakeTextEncoder())
    # Two rows: aerial at 0.30, its null at 0.34. Over the threshold, under the null.
    row = np.zeros((1, WIDTH), dtype=np.float32)
    row[0, 0], row[0, 1] = 0.30, 0.34

    probabilities = tag_embeddings(row, encoded_single, SCALE, 0.2, 3)[0]
    assert probabilities == []

    # The same shot with the two cosines swapped does produce the tag.
    row[0, 0], row[0, 1] = 0.34, 0.30
    assert [tag.label for tag in tag_embeddings(row, encoded_single, SCALE, 0.2, 3)[0]] == [
        "aerial"
    ]


def test_without_a_null_prompt_some_label_would_always_win() -> None:
    """The reason the null prompt exists, stated as a test.

    The same vector that reads as nothing against a group with a null prompt reads as a
    label against one without it, because the probabilities have to sum to one over
    whatever rows are there.
    """
    with_null = encoded()
    without_null = encode_groups(GROUPS, FakeTextEncoder())
    without_null[0].matrix = without_null[0].matrix[:2]

    shot = leaning(SUBJECT_NULL, BEACH, 0.9)[None, :]
    assert tag_embeddings(shot, with_null, SCALE, 0.2, 3)[0] == []
    assert tag_embeddings(shot, without_null, SCALE, 0.2, 3)[0] != []


def test_a_subject_and_a_view_do_not_compete() -> None:
    """A drone shot over a beach is both, which is what the groups are for."""
    both = vector(**{str(BEACH): 0.7, str(AERIAL): 0.7})
    tags = tag_embeddings(both[None, :], encoded(), SCALE, 0.2, 3)[0]

    labels = {tag.label: tag for tag in tags}
    assert set(labels) == {"beach", "aerial"}
    assert labels["beach"].primary
    assert not labels["aerial"].primary
    assert labels["aerial"].group == "view"


def test_the_dominant_tag_comes_first_even_when_a_view_tag_is_surer() -> None:
    row = vector(**{str(BEACH): 0.45, str(SUBJECT_NULL): 0.4, str(AERIAL): 0.9})
    tags = tag_embeddings(row[None, :], encoded(), SCALE, 0.2, 3)[0]

    assert tags[0].label == "beach"
    assert tags[0].primary
    assert tags[1].confidence > tags[0].confidence


def test_the_cap_counts_across_groups_and_spares_the_dominant_tag() -> None:
    row = vector(**{str(BEACH): 0.5, str(FOOD): 0.45, str(AERIAL): 0.9})
    tags = tag_embeddings(row[None, :], encoded(), SCALE, 0.2, 2)[0]

    assert len(tags) == 2
    assert tags[0].label == "beach"


def test_a_cap_of_zero_keeps_nothing() -> None:
    row = leaning(BEACH, SUBJECT_NULL, 0.9)
    assert tag_embeddings(row[None, :], encoded(), SCALE, 0.2, 0)[0] == []


def test_the_logit_scale_decides_whether_a_threshold_means_anything() -> None:
    """At CLIP's own scale of 100 the softmax is one-hot and nothing is ever rejected."""
    # A shot the model is mildly sure about: 0.62 at scale 10, 0.99 at scale 100.
    row = leaning(BEACH, SUBJECT_NULL, 0.62)[None, :]

    at_ten = tag_embeddings(row, encoded(), 10.0, 0.9, 3)[0]
    at_hundred = tag_embeddings(row, encoded(), 100.0, 0.9, 3)[0]

    assert at_ten == []
    assert [tag.label for tag in at_hundred] == ["beach"]
    assert at_hundred[0].confidence > 0.99


def test_no_embeddings_gives_no_tags() -> None:
    assert tag_embeddings(np.zeros((0, WIDTH), dtype=np.float32), encoded(), SCALE, 0.2, 3) == []


def test_a_label_without_a_prompt_uses_the_group_template() -> None:
    assert prompt_for(TagLabel(label="beach"), "a photo of {label}") == "a photo of beach"
    assert prompt_for(VIEW.labels[0], "a photo of {label}").startswith("an aerial photo")


def test_tagging_a_project_fills_every_embedded_segment(tmp_path: Path) -> None:
    vectors = np.stack(
        [
            leaning(BEACH, SUBJECT_NULL, 0.62),
            leaning(FOOD, SUBJECT_NULL, 0.80),
            leaning(SUBJECT_NULL, BEACH, 0.9),
        ]
    )
    manifest = project_with(tmp_path, vectors)

    result = tag_project(manifest, config_in(tmp_path), encoder=FakeTextEncoder())

    assert not result.skipped
    assert result.embedded == 3
    assert result.with_a_tag == 2
    assert result.with_a_subject == 2
    assert result.groups == 2
    assert result.labels == 3
    assert manifest.segments["aaa:0"].dominant_tag == "beach"
    assert manifest.segments["aaa:1"].dominant_tag == "food"
    assert manifest.segments["aaa:2"].tags == []
    assert result.counts == {"beach": 1, "food": 1}
    assert result.per_group == {"subject": {"beach": 1, "food": 1}}


def test_the_per_group_counts_name_every_group_that_fired(tmp_path: Path) -> None:
    manifest = project_with(tmp_path, np.stack([vector(**{str(BEACH): 0.7, str(AERIAL): 0.7})]))

    result = tag_project(manifest, config_in(tmp_path), encoder=FakeTextEncoder())

    assert result.per_group == {"subject": {"beach": 1}, "view": {"aerial": 1}}


def test_a_view_tag_alone_leaves_the_clip_without_a_name(tmp_path: Path) -> None:
    """Aerial says how it was shot, not what it shows, so the name stays clip."""
    row = vector(**{str(SUBJECT_NULL): 0.6, str(AERIAL): 0.9})
    manifest = project_with(tmp_path, np.stack([row]))

    tag_project(manifest, config_in(tmp_path), encoder=FakeTextEncoder())

    segment = manifest.segments["aaa:0"]
    assert [tag.label for tag in segment.tags] == ["aerial"]
    assert segment.dominant_tag is None
    assert [tag.label for tag in segment.secondary_tags] == ["aerial"]


def test_a_project_without_embeddings_is_skipped(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(
        CacheEntry(
            file_key="aaa",
            source="original",
            arrays={"timestamps": np.arange(2, dtype=np.float64)},
            shot_bounds=[(0.0, 1.0), (1.0, 2.0)],
            thumb_frames=np.zeros((2, 4, 4, 3), dtype=np.uint8),
        ),
        config,
    )
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "out"
    )
    manifest.segments["aaa:0"] = Segment(id="aaa:0", file_id="aaa", start_s=0.0, end_s=1.0)

    result = tag_project(manifest, config, encoder=FakeTextEncoder())

    assert result.skipped
    assert result.skipped_reason is not None
    assert "embedding" in result.skipped_reason


def test_tagging_disabled_by_configuration(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    config.tags.enabled = False
    manifest = project_with(tmp_path, np.stack([leaning(BEACH, SUBJECT_NULL, 0.62)]))

    result = tag_project(manifest, config, encoder=FakeTextEncoder())

    assert result.skipped
    assert result.skipped_reason is not None
    assert "disabled" in result.skipped_reason


def test_an_empty_label_set_is_skipped(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    config.tags.groups = [TagGroup(name="empty", null_prompt="a photo", labels=[])]
    manifest = project_with(tmp_path, np.stack([leaning(BEACH, SUBJECT_NULL, 0.62)]))

    result = tag_project(manifest, config, encoder=FakeTextEncoder())

    assert result.skipped
    assert result.skipped_reason is not None
    assert "labels" in result.skipped_reason


def test_re_tagging_replaces_local_tags_and_keeps_the_others(tmp_path: Path) -> None:
    manifest = project_with(tmp_path, np.stack([leaning(BEACH, SUBJECT_NULL, 0.62)]))
    segment = manifest.segments["aaa:0"]
    segment.tags = [
        Tag(label="snorkeling", confidence=1.0, source="cloud"),
        Tag(label="stale", confidence=0.9, source="local", primary=True),
    ]

    tag_project(manifest, config_in(tmp_path), encoder=FakeTextEncoder())

    labels = {tag.label: tag.source for tag in segment.tags}
    assert "stale" not in labels
    assert labels["snorkeling"] == "cloud"
    assert labels["beach"] == "local"


def test_a_segment_without_a_vector_loses_its_local_tags(tmp_path: Path) -> None:
    """A shot with no embedding must not keep a tag computed from an older one."""
    manifest = project_with(tmp_path, np.stack([leaning(BEACH, SUBJECT_NULL, 0.62)]), count=1)
    manifest.segments["bbb:0"] = Segment(id="bbb:0", file_id="bbb", start_s=0.0, end_s=1.0)
    manifest.segments["bbb:0"].tags = [
        Tag(label="beach", confidence=0.9, source="local", primary=True)
    ]

    result = tag_project(manifest, config_in(tmp_path), encoder=FakeTextEncoder())

    assert manifest.segments["bbb:0"].tags == []
    assert result.without_an_embedding == 1
    assert result.embedded == 1


def test_progress_reports_one_event_per_segment(tmp_path: Path) -> None:
    manifest = project_with(
        tmp_path,
        np.stack([leaning(BEACH, SUBJECT_NULL, 0.62), leaning(SUBJECT_NULL, BEACH, 0.9)]),
    )
    events: list[ProgressEvent] = []

    tag_project(manifest, config_in(tmp_path), events.append, encoder=FakeTextEncoder())

    assert len(events) == 2
    assert {event.stage for event in events} == {"tag"}
    assert [event.current for event in events] == [1, 2]


def test_an_empty_result_reports_nothing_tagged() -> None:
    assert TagResult().model == "none"
    assert not TagResult().skipped

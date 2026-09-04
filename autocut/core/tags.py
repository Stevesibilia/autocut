"""Zero-shot semantic tags from the segment embeddings and a configurable label set.

Every exported clip was called ``clip``, selection could not tell a beach from a plate
of food, and the M4 soundtrack prompt had nothing to say about what the video shows.
With the embeddings from ``m3-embeddings`` in the cache, a tag costs one text encoding
per label and no second model: the image tower and the text tower are the same
checkpoint, so tagging a few hundred segments is a matrix product.

Three decisions came out of measuring this on real footage rather than from theory.

**Labels are grouped and each group gets its own softmax.** A drone shot over a beach
is a beach and is aerial. One softmax over both makes them compete for the same
probability mass, and on the Sardinia set ``beach`` won all 27 drone segments while
``aerial`` never appeared. Anything that can be true at the same time as another label
belongs in another group.

**Every group carries a null prompt** that joins its softmax, is never emitted, and has
to be beaten before any label is. Without it a group's probabilities sum to one over its
labels alone, so some label always wins however little the picture has to do with any of
them. And a threshold on its own is not enough: what a probability of 0.2 means depends
on how many rows the group has, so on a two row group it accepts everything. Measured on
the Sardinia set, the threshold alone put ``sunset`` on all 77 segments; requiring it to
beat its own null prompt puts it on none, which is the right answer for footage with no
sunset in it.

**The logit scale is configurable and defaults to 10, not to CLIP's 100.** 100 is the
constant the contrastive loss was trained with; over a handful of labels it produces a
one-hot distribution. Measured at 100, all 77 real segments took a tag, the median top
probability was 0.977 and the threshold rejected nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from autocut.core.cache import read_entry, thumb_index
from autocut.core.config import AutocutConfig, TagGroup, TagLabel
from autocut.core.embeddings import (
    EmbeddingsUnavailableError,
    TextEncoder,
    available,
    load_model,
    normalize,
    text_encoder,
)
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.manifest import Manifest, Tag


@dataclass(slots=True)
class TagResult:
    """What one tagging pass did, for the run summary and the CLI."""

    model: str = "none"
    labels: int = 0
    groups: int = 0
    embedded: int = 0
    with_a_tag: int = 0
    with_a_subject: int = 0
    without_an_embedding: int = 0
    skipped_reason: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    per_group: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


@dataclass(slots=True)
class EncodedGroup:
    """One group's label matrix, with its null row last."""

    group: TagGroup
    matrix: np.ndarray

    @property
    def labels(self) -> list[TagLabel]:
        return list(self.group.labels)


def prompt_for(label: TagLabel, template: str) -> str:
    """The sentence a label is encoded as."""
    return label.prompt or template.format(label=label.label)


def group_prompts(group: TagGroup) -> list[str]:
    """Every sentence a group encodes, its null prompt last."""
    return [prompt_for(label, group.prompt_template) for label in group.labels] + [
        group.null_prompt
    ]


def encode_groups(groups: list[TagGroup], encoder: TextEncoder) -> list[EncodedGroup]:
    """One normalized matrix per group, labels in order and the null prompt last.

    All groups are encoded in one call, because the cost of the text tower is dominated
    by loading it rather than by the handful of prompts it is given.
    """
    live = [group for group in groups if group.labels]
    if not live:
        return []
    prompts: list[str] = []
    for group in live:
        prompts.extend(group_prompts(group))
    vectors = normalize(np.atleast_2d(np.asarray(encoder(prompts), dtype=np.float32)))
    encoded: list[EncodedGroup] = []
    offset = 0
    for group in live:
        width = len(group.labels) + 1
        encoded.append(EncodedGroup(group=group, matrix=vectors[offset : offset + width]))
        offset += width
    return encoded


def tag_embeddings(
    embeddings: np.ndarray,
    encoded: list[EncodedGroup],
    logit_scale: float,
    threshold: float,
    max_per_segment: int,
) -> list[list[Tag]]:
    """Tags for each row of ``embeddings``, the dominant one first.

    A label is emitted when it clears ``threshold`` and beats its group's null prompt.
    Both conditions are needed. The threshold alone means different things in a group of
    two rows and a group of eight, and beating the null alone would emit a label that
    won by a hair over a field of near ties. A row whose every group answers with its
    null prompt gets an empty list, which is what makes an ambiguous shot fall back to
    the ``clip`` name rather than to a bad guess.
    """
    rows = int(embeddings.shape[0]) if embeddings.ndim > 1 else 0
    if embeddings.size == 0 or not encoded:
        return [[] for _ in range(rows)]

    per_row: list[list[Tag]] = [[] for _ in range(rows)]
    for entry in encoded:
        probabilities = _softmax(logit_scale * (np.atleast_2d(embeddings) @ entry.matrix.T))
        labels = entry.labels
        for index, row in enumerate(probabilities):
            # The last column is the null prompt: it competes, decides, and is never
            # emitted.
            null = row[-1]
            for position, label in enumerate(labels):
                if row[position] >= threshold and row[position] > null:
                    per_row[index].append(
                        Tag(
                            label=label.label,
                            confidence=float(row[position]),
                            source="local",
                            group=entry.group.name,
                            primary=entry.group.primary,
                        )
                    )
    return [_keep(tags, max_per_segment) for tags in per_row]


def _keep(tags: list[Tag], max_per_segment: int) -> list[Tag]:
    """The dominant tag first, then the rest by confidence, up to the cap.

    The cap is across groups rather than per group, and the dominant tag is exempt from
    it: a clip whose subject was recognized must keep the label that names its file.
    """
    if max_per_segment <= 0:
        return []
    ordered = sorted(tags, key=lambda tag: tag.confidence, reverse=True)
    dominant = next((tag for tag in ordered if tag.primary), None)
    if dominant is None:
        return ordered[:max_per_segment]
    rest = [tag for tag in ordered if tag is not dominant]
    return [dominant, *rest[: max_per_segment - 1]]


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return np.asarray(exponentials / exponentials.sum(axis=1, keepdims=True), dtype=np.float64)


def tag_project(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
    encoder: TextEncoder | None = None,
) -> TagResult:
    """Recompute the local tags of every embedded segment, from the cache alone.

    Only ``local`` tags are replaced. Tags from another source stay where they are, so
    re-running this after ``m3-cloud-providers`` has described a project costs nothing
    but the local labels.
    """
    if not config.tags.enabled:
        return TagResult(skipped_reason="tagging is disabled by configuration")
    groups = [group for group in config.tags.groups if group.labels]
    if not groups:
        return TagResult(skipped_reason="no labels are configured")

    vectors = _embeddings_by_segment(manifest, config)
    if not vectors:
        return TagResult(
            skipped_reason="no segment has an embedding, run autocut embed first",
            without_an_embedding=len(manifest.segments),
        )

    if encoder is None:
        reason = available()
        if reason is not None:
            return TagResult(skipped_reason=reason)
        try:
            encoder = text_encoder(load_model(config))
        except EmbeddingsUnavailableError as exc:
            return TagResult(skipped_reason=str(exc))

    encoded = encode_groups(groups, encoder)
    segment_ids = list(vectors)
    assigned = tag_embeddings(
        np.stack([vectors[segment_id] for segment_id in segment_ids]),
        encoded,
        config.tags.logit_scale,
        config.tags.threshold,
        config.tags.max_per_segment,
    )

    result = TagResult(
        model=config.providers.embedding_model,
        labels=sum(len(group.labels) for group in groups),
        groups=len(groups),
    )
    total = len(segment_ids)
    for position, (segment_id, tags) in enumerate(zip(segment_ids, assigned, strict=True), start=1):
        segment = manifest.segments[segment_id]
        segment.tags = [tag for tag in segment.tags if tag.source != "local"] + tags
        segment.tags.sort(key=lambda tag: (not tag.primary, -tag.confidence))
        result.embedded += 1
        if tags:
            result.with_a_tag += 1
        if segment.dominant_tag is not None:
            result.with_a_subject += 1
        progress(ProgressEvent(stage="tag", current=position, total=total))

    for segment in manifest.segments.values():
        if segment.id not in vectors:
            segment.tags = [tag for tag in segment.tags if tag.source != "local"]
            result.without_an_embedding += 1
    result.counts = dominant_counts(manifest)
    result.per_group = group_counts(manifest)
    return result


def dominant_counts(manifest: Manifest) -> dict[str, int]:
    """How many segments carry each dominant tag, most common first."""
    counts: dict[str, int] = {}
    for segment in manifest.segments.values():
        dominant = segment.dominant_tag
        if dominant is not None:
            counts[dominant] = counts.get(dominant, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def group_counts(manifest: Manifest) -> dict[str, dict[str, int]]:
    """How many segments carry each label, per group, most common first."""
    counts: dict[str, dict[str, int]] = {}
    for segment in manifest.segments.values():
        for tag in segment.tags:
            group = counts.setdefault(tag.group or "ungrouped", {})
            group[tag.label] = group.get(tag.label, 0) + 1
    return {
        name: dict(sorted(labels.items(), key=lambda item: (-item[1], item[0])))
        for name, labels in counts.items()
    }


def _embeddings_by_segment(manifest: Manifest, config: AutocutConfig) -> dict[str, np.ndarray]:
    """The vector of every segment that has one, reading each cache entry once."""
    vectors: dict[str, np.ndarray] = {}
    by_file: dict[str, list[str]] = {}
    for segment in manifest.segments.values():
        by_file.setdefault(segment.file_id, []).append(segment.id)
    for file_id, segment_ids in by_file.items():
        entry = read_entry(file_id, config)
        if entry is None or entry.embeddings is None or entry.embeddings.size == 0:
            continue
        rows = int(entry.embeddings.shape[0])
        for segment_id in segment_ids:
            index = thumb_index(segment_id, rows)
            if index >= 0:
                vectors[segment_id] = entry.embeddings[index]
    return vectors

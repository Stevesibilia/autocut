## Why

Every exported clip is still named `clip`, selection cannot balance beach against food against people, and the soundtrack prompt planned for M4 has nothing to say about what the video shows. With embeddings in place, zero-shot tags cost one text encoding per label and no extra model. SPEC.md section 8 module 3 names this as the next step after embeddings.

## What Changes

- Zero-shot semantic tags per segment from the configured label set, computed locally from the segment embedding and the text embeddings of the labels, with a confidence threshold and a maximum count.
- Label set in configuration with shipped defaults (`aerial`, `sunset`, `beach`, `mountain`, `people`, `food`, `city`, `underwater`, `indoor`, `street`), user editable.
- Tags stored on the segment with their confidence and their source (`local` now, `cloud` in the next change).
- Category balance in selection: at most `selection.max_share_per_tag` of the final count may carry the same dominant tag when enough candidates with other tags exist.
- Output names use the dominant tag in place of `clip`.
- Report shows tags on every card and filters by tag; summary header counts segments per tag.
- `autocut tag <project>` recomputes tags from cached embeddings without re-analysis, so editing the label set is instant.

## Capabilities

### New Capabilities

- `semantic-tags`: assigning labels with confidence to segments from their embeddings and a configurable label set.

### Modified Capabilities

- `clip-selection`: a per-tag share cap joins the caps and quotas.
- `output-naming`: the tag field is the dominant tag.
- `review-report`: tags shown, tag filter and tag counts.

## Impact

- New module `autocut/core/tags.py`; `select.py`, `naming.py`, `report.py` and the template gain tag handling.
- `autocut/core/config.py`: `tags.labels`, `tags.threshold`, `tags.max_per_segment`, `selection.max_share_per_tag`.
- `autocut/core/manifest.py`: `Segment.tags` becomes a list of `Tag(label, confidence, source)`; `MANIFEST_SCHEMA_VERSION` stays 1 with a loader that upgrades a plain string list.
- Depends on `m3-embeddings`. Without embeddings, tagging is skipped with one warning and names stay `clip`.

## Context

`m3-embeddings` leaves a normalized 512-dimension CLIP image embedding per segment in the cache and the CLIP text tower loadable through the same module. Zero-shot classification is a matrix product between those and the encoded labels. Selection, naming and the report already have the hooks (`tags` list, `{tag}` placeholder, card fields).

## Goals / Non-Goals

**Goals:**

- Tags in under two seconds for hundreds of segments, so editing the label list is an interactive loop.
- A tag schema that a cloud source can merge into without a migration.

**Non-Goals:**

- Captions and cloud tags (change `m3-cloud-providers`).
- Training or fine tuning labels.

## Decisions

**Prompt templates.** Each label is encoded as `a photo of {label}` by default, overridable per label (`aerial` uses `an aerial photo of a landscape`). Templates matter for CLIP and the defaults are shipped in config so tuning needs no code.

**Softmax with temperature.** Logits are cosine similarities times 100, the CLIP convention, then softmax over the label set. Threshold 0.2 and max 3 tags by default. Alternative, raw cosine thresholds, rejected because the useful range shifts with the label set.

**Tag model.** `Tag(label: str, confidence: float, source: Literal["local", "cloud"])`. The manifest loader accepts a legacy list of strings and upgrades it to `local` tags with confidence 1.0, so `MANIFEST_SCHEMA_VERSION` stays 1.

**Dominant tag.** The first tag after sorting by confidence descending, used by naming and by the selection share cap. Stored as a derived property, not a field.

**Share cap in selection.** Implemented as one more eligibility filter next to the cluster cap: a candidate is ineligible while `selected_with_same_dominant_tag / max_clips >= max_share_per_tag` and another eligible candidate exists with a different or no dominant tag. Default 0.5. Lifted in the same last-resort pass that relaxes the temporal gap.

**Where tagging runs.** `autocut tag` is a separate command and is called at the end of `autocut analyze` after `embed`. Text embeddings for the label set are cached in memory per run only; encoding ten labels costs milliseconds.

## Risks / Trade-offs

- [CLIP zero-shot confuses `beach` and `underwater` on Sardinian water] → validation records the confusion on real footage; label prompts are tunable in config.
- [Label set change invalidates nothing but tags] → intended; tags are cheap and derived.
- [Tag share cap fights class share] → class share is a floor applied first, tag cap is a ceiling applied during the open field; documented order in the design of `m2-select` is extended, not changed.

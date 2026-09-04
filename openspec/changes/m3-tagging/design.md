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

**Prompt templates.** Each label is encoded as `a photo of {label}` by default, overridable per label (`aerial` uses `an aerial photo taken from a drone`). Templates matter for CLIP and the defaults are shipped in config so tuning needs no code.

**Label groups, one softmax each.** The first implementation put all ten labels in one softmax with CLIP's logit scale of 100, and the measurement on the real footage rejected that design three times over.

At scale 100 the distribution is one-hot: the median top probability was 0.977, the minimum 0.493, and **0 of 77 segments** ever fell below the 0.2 threshold. Both `tags.threshold` and `tags.max_per_segment` were inert, 64 segments took exactly one tag and 13 took two, and the spec's ambiguous shot, the one that falls back to `clip`, could not happen at all. The scale is therefore a config field, `tags.logit_scale`, defaulting to 10. 100 is the constant CLIP's contrastive loss was trained with and has no claim on a softmax over ten words.

One softmax over all ten labels also made labels that are simultaneously true fight each other. A drone shot over a beach is a beach and is aerial; with both in one distribution `beach` took all 27 drone segments and `aerial` appeared on none, at raw cosines of 0.2886 against 0.2052. Labels are therefore grouped, one softmax per group, and anything that can be true at the same time as another label goes in another group: `subject`, `view` and `light`. Only the primary group, `subject`, names a clip, because `aerial` says what the source class already says.

**Null prompt, and why a threshold alone is not enough.** Each group carries a null prompt that joins its softmax and is never emitted. Without it the probabilities of a group sum to one over its labels alone, so some label always wins.

Adding the null row was still not enough, because what a probability of 0.2 means depends on how many rows the group has. Uniform is 0.125 over the eight subject rows and 0.5 over the two light rows, so the threshold that discriminates in one group accepts everything in the other: measured, `sunset` was emitted on all 77 segments and `underwater` on 70. Prompt rewording moved those numbers by single digits and was not the problem. A label is therefore kept only when it clears the threshold **and** beats its own group's null prompt, which is the rule the null row was introduced for. That puts `sunset` on 0 segments, correct for footage with no sunset in it, and `underwater` on 20.

**Threshold and cap.** Threshold 0.2 and max 3 tags by default, the cap counted across groups with the dominant tag kept first. Alternative, raw cosine thresholds, rejected because the useful range shifts with the label set.

**Tag model.** `Tag(label: str, confidence: float, source: Literal["local", "cloud"])`. The manifest loader accepts a legacy list of strings and upgrades it to `local` tags with confidence 1.0, so `MANIFEST_SCHEMA_VERSION` stays 1.

**Dominant tag.** The highest confidence tag from the primary group, used by naming and by the selection share cap. Derived rather than stored, but each tag carries a `primary` flag so a manifest opened without the configuration that produced it still names its clips the way it exported them.

**Share cap in selection.** Implemented as one more eligibility filter next to the cluster cap: a candidate is ineligible while `selected_with_same_dominant_tag / max_clips >= max_share_per_tag` and another eligible candidate exists with a different or no dominant tag. Default 0.5. Lifted in the same last-resort pass that relaxes the temporal gap.

**Where tagging runs.** `autocut tag` is a separate command and is called at the end of `autocut analyze` after `embed`. Text embeddings for the label set are cached in memory per run only; encoding ten labels costs milliseconds.

## Risks / Trade-offs

- [CLIP zero-shot confuses `beach` and `underwater` on Sardinian water] → measured and confirmed: 5 of the 20 `underwater` tags are drone shots of clear water from above. Label prompts are tunable in config, and the confusion costs nothing today because `underwater` is a secondary tag that names no file and enters no cap.
- [Label set change invalidates nothing but tags] → intended; tags are cheap and derived.
- [Tag share cap fights class share] → class share is a floor applied first, tag cap is a ceiling applied during the open field; documented order in the design of `m2-select` is extended, not changed.

# semantic-tags Specification

## Purpose

Semantic tags say what a segment shows in a handful of configurable words, so names, selection balance, filters and the soundtrack prompt can use them.

## Requirements

### Requirement: Zero-shot tags from grouped labels

For every segment with an embedding the system SHALL compute the cosine similarity to the text embedding of each configured prompt, and SHALL convert those to probabilities with one softmax per label group rather than one over the whole label set. Labels that can be true at the same time MUST live in different groups.

#### Scenario: Beach shot

- **WHEN** a segment's embedding is closest to the label `beach` in the subject group with probability 0.62 and the threshold is 0.2
- **THEN** its first tag is `beach` with confidence 0.62

#### Scenario: A subject and a view do not compete

- **WHEN** a drone segment shows a beach from the air, `beach` is in the subject group and `aerial` is in the view group
- **THEN** the segment carries both tags

### Requirement: Null prompt per group

Each group SHALL carry a `null_prompt` that takes part in its softmax and is never emitted as a tag. A label SHALL be kept only when its probability reaches `tags.threshold` and is higher than the null prompt's. Both conditions are required: a probability threshold alone means something different in a group of two rows and a group of eight, and beating the null alone would emit a label that won by a hair over a field of near ties.

#### Scenario: None of these

- **WHEN** every group answers with its null prompt
- **THEN** the segment has no tags and its name falls back to `clip`

#### Scenario: A label that clears the threshold but loses to the null

- **WHEN** a two label group scores `sunset` at 0.31 and its null prompt at 0.69, with a threshold of 0.2
- **THEN** `sunset` is not emitted

### Requirement: Configurable logit scale

Cosines SHALL be multiplied by `tags.logit_scale` before the softmax, defaulting to 10. CLIP's own constant of 100 belongs to its contrastive loss and MUST NOT be assumed here: over a handful of labels it produces a one-hot distribution in which no threshold can reject anything.

#### Scenario: The scale decides whether the threshold means anything

- **WHEN** the same segment is scored at scale 100 and at scale 10
- **THEN** the top probability is above 0.99 at 100 and spread widely enough at 10 for the threshold to reject a weak label

### Requirement: Configurable label groups

Groups SHALL come from `tags.groups`, each with a name, a prompt template (default `a photo of {label}`), a null prompt, a `primary` flag and its labels, each label with an optional prompt of its own. The shipped groups are `subject` (beach, mountain, city, street, indoor, food, people), `view` (aerial, underwater) and `light` (sunset). Changing the groups and re-running `autocut tag` MUST recompute tags without touching embeddings or metrics.

#### Scenario: Custom label

- **WHEN** the user adds `boat` to a group and runs `autocut tag`
- **THEN** segments showing boats gain the `boat` tag and no decoding or embedding runs

### Requirement: Dominant tag from the primary group

The dominant tag, the one that names the exported clip, SHALL be the highest confidence tag from the group marked `primary`. Tags from other groups SHALL be secondary and MUST NOT name a file: a view or a lighting condition says how a shot was taken, not what it shows, and the source class already carries the former. `tags.max_per_segment` SHALL cap the total number of tags across groups, keeping the dominant tag first.

#### Scenario: A view tag alone does not name a clip

- **WHEN** a segment is confidently `aerial` and no subject label beats its null prompt
- **THEN** the segment carries `aerial` as a secondary tag, has no dominant tag, and is named `clip`

#### Scenario: Ordered and capped

- **WHEN** a segment reaches three labels across two groups and `max_per_segment` is 2
- **THEN** the dominant tag is kept and one other, the more confident of the rest

### Requirement: Tag provenance

Each tag SHALL record its source (`local` or `cloud`) and confidence. Local and cloud tags SHALL coexist on a segment; re-running the local tagger replaces only `local` tags and re-running descriptions replaces only `cloud` tags. The dominant tag SHALL be the first cloud tag when any exists, otherwise the highest confidence local tag.

#### Scenario: Stored tag

- **WHEN** a tag is written by the local tagger
- **THEN** it has `source: local` and a confidence in 0 to 1

#### Scenario: Cloud tag dominates

- **WHEN** a segment has local tag `beach` 0.62 and cloud tags `snorkeling`, `beach`
- **THEN** the dominant tag is `snorkeling`

#### Scenario: Re-tag keeps cloud

- **WHEN** `autocut tag` runs again after descriptions exist
- **THEN** cloud tags are unchanged and local tags are recomputed

### Requirement: Tag command

`autocut tag <project>` SHALL compute tags for all segments with embeddings and SHALL be called by `autocut analyze` after embedding when tagging is enabled.

#### Scenario: Tag after the fact

- **WHEN** a project has embeddings and no tags
- **THEN** `autocut tag` fills tags for every embedded segment in under two seconds for 500 segments

#### Scenario: No embedding

- **WHEN** the project has no embeddings
- **THEN** no segment is tagged and the CLI prints one line saying tagging was skipped

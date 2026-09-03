## Purpose

Semantic tags say what a segment shows in a handful of configurable words, so names, selection balance, filters and the soundtrack prompt can use them.

## ADDED Requirements

### Requirement: Zero-shot tags from embeddings

For every segment with an embedding the system SHALL compute the cosine similarity to the text embedding of each configured label, convert to probabilities with a softmax over the label set, and keep labels above `tags.threshold` up to `tags.max_per_segment`, ordered by confidence. Segments without an embedding MUST keep an empty tag list.

#### Scenario: Beach shot

- **WHEN** a segment's embedding is closest to the label `beach` with probability 0.62 and the threshold is 0.2
- **THEN** its first tag is `beach` with confidence 0.62

#### Scenario: Ambiguous shot

- **WHEN** no label reaches the threshold
- **THEN** the segment has no tags and its name falls back to `clip`

#### Scenario: No embedding

- **WHEN** the project has no embeddings
- **THEN** no segment is tagged and the CLI prints one line saying tagging was skipped

### Requirement: Configurable label set

Labels SHALL come from `tags.labels`, each with an optional prompt template (default `a photo of {label}`), with shipped defaults covering aerial, sunset, beach, mountain, people, food, city, underwater, indoor and street. Changing the label set and re-running `autocut tag` MUST recompute tags without touching embeddings or metrics.

#### Scenario: Custom label

- **WHEN** the user adds `boat` to `tags.labels` and runs `autocut tag`
- **THEN** segments showing boats gain the `boat` tag and no decoding or embedding runs

### Requirement: Tag provenance

Each tag SHALL record its source (`local` or `cloud`) and confidence, and a later source MUST NOT silently delete tags from another source; the merge rule belongs to the change that introduces the second source.

#### Scenario: Stored tag

- **WHEN** a tag is written by the local tagger
- **THEN** it has `source: local` and a confidence in 0 to 1

### Requirement: Tag command

`autocut tag <project>` SHALL compute tags for all segments with embeddings and SHALL be called by `autocut analyze` after embedding when tagging is enabled.

#### Scenario: Tag after the fact

- **WHEN** a project has embeddings and no tags
- **THEN** `autocut tag` fills tags for every embedded segment in under two seconds for 500 segments

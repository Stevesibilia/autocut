## Purpose

Segment descriptions add what a hosted vision model sees in a shot: specific tags, a one-sentence caption and an aesthetic judgment, for names, balance, the report and the soundtrack prompt.

## ADDED Requirements

### Requirement: One structured description per segment

For each segment in scope (`providers.describe_scope`, default `candidates`, alternative `selected`) the system SHALL request from the vision model a JSON object with `tags` (up to five, from the configured label set first, then free words), `caption` (one sentence, at most 20 words, lowercase), and `aesthetic` (integer 1 to 10), and SHALL validate the shape before storing. An invalid response SHALL be retried once with a correction prompt and then recorded as a failure.

#### Scenario: Valid response

- **WHEN** the model returns `{"tags": ["beach", "snorkeling"], "caption": "two people snorkeling over clear turquoise water", "aesthetic": 7}`
- **THEN** the segment gains two cloud tags, the caption and aesthetic 7

#### Scenario: Invalid response

- **WHEN** the model returns prose instead of JSON twice
- **THEN** the segment records a description failure and the run continues

### Requirement: Stored fields

The caption SHALL be stored on `Segment.caption`, the aesthetic value on `Metrics.aesthetic` scaled to 0 to 1, and cloud tags on `Segment.tags` with `source: cloud` and confidence 1.0 in the order returned.

#### Scenario: Aesthetic in score

- **WHEN** `weights.aesthetic` is 1.0 and descriptions exist
- **THEN** the composite score includes the aesthetic value with the same per-class rank normalization as other metrics

#### Scenario: Aesthetic weight zero

- **WHEN** `weights.aesthetic` is 0
- **THEN** descriptions do not change any score

### Requirement: Describe command

`autocut describe <project>` SHALL run descriptions for segments in scope that have no cached response, and `autocut analyze` SHALL call it after tagging when cloud is enabled and a key is present.

#### Scenario: Describe selected only

- **WHEN** `providers.describe_scope` is `selected` and 40 segments are selected
- **THEN** at most 40 requests are made

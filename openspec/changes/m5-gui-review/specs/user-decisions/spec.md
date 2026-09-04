## Purpose

User decisions record what a person said about a segment so that no automatic step undoes it.

## ADDED Requirements

### Requirement: Keep and reject pins

A segment MAY carry a user decision `keep` or `reject`. Selection SHALL always select a `keep` segment (counting it against caps but never excluding it for them) and SHALL never select a `reject` segment. Rejection rules and similarity MUST NOT change a pinned decision. Pins SHALL persist in the manifest and survive `autocut select` and re-analysis from cache.

#### Scenario: Kept clip survives the slider

- **WHEN** a user keeps a segment and the diversity slider moves
- **THEN** the segment stays selected

#### Scenario: Rejected clip stays out

- **WHEN** a user rejects the highest scoring segment and select runs again
- **THEN** it is not selected and the next candidate takes the slot

### Requirement: Custom bounds

A segment MAY carry user in and out points inside its trimmed span. When present they SHALL replace the best window and the assigned duration for export and beat sync, and beat sync SHALL quantize around their center without extending past them.

#### Scenario: Trimmed by hand

- **WHEN** a user sets in 4.0 s and out 6.5 s on a segment
- **THEN** export cuts 4.0 to 6.5 and the report shows `user` as the duration reason

### Requirement: Clearing a decision

A user decision MAY be cleared, after which the segment returns to automatic handling on the next select.

#### Scenario: Undo keep

- **WHEN** a keep is cleared and select runs
- **THEN** the segment competes on score like any other

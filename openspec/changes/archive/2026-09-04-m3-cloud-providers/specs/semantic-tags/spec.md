## MODIFIED Requirements

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

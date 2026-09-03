## MODIFIED Requirements

### Requirement: One card per segment

Each segment in the manifest SHALL appear as a card showing thumbnail, source file name, class and deciding signal, start and end time, duration, composite score, each per-metric value, outcome and rejection reason when rejected. Selected segments SHALL show their order, best window, target duration and the reason for that duration, and SHALL be listed first when sorting by chronology. Candidates that lost to a near duplicate SHALL show which selected segment they lost to. Rejected segments MUST be visually distinct from candidates and selected segments from both.

#### Scenario: Rejected card

- **WHEN** a segment has outcome `rejected` with reason `low_altitude`
- **THEN** its card shows the reason and is styled as rejected

#### Scenario: Selected card

- **WHEN** a segment has outcome `selected` with order 12
- **THEN** its card shows `012`, the best window bounds and is styled as selected

#### Scenario: Lost duplicate

- **WHEN** a candidate has `lost_to` set
- **THEN** its card names the selected segment it lost to and its cluster

#### Scenario: Duration reason

- **WHEN** a selected segment has target duration 4.8 s with reason `hero`
- **THEN** its card shows `4.8 s` and `hero`

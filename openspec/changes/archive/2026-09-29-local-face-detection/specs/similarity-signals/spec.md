## ADDED Requirements

### Requirement: Face-count guard

When `similarity.face_guard` is on and two segments both have a face count and the counts differ, their combined similarity SHALL be 0, whatever the other signals say. When either count is absent, the guard SHALL NOT apply.

#### Scenario: Same place, different people

- **WHEN** two segments of the same beach a minute apart have face counts 0 and 2 and would otherwise be 0.9 similar
- **THEN** their similarity is 0, they fall in different clusters, and neither penalises the other in selection

#### Scenario: Counts unknown

- **WHEN** face detection was off for either segment
- **THEN** their similarity is computed from the signals as before

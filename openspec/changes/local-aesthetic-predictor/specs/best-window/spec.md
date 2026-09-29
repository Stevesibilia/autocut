## ADDED Requirements

### Requirement: Segment-only metrics do not shape the window

A scored metric that has no per-frame array, such as `aesthetic`, SHALL be left out of the per-frame window score, whatever its weight, and SHALL still count in the segment's composite score.

#### Scenario: Aesthetic weighted

- **WHEN** selection runs with `weights.aesthetic = 1.0`
- **THEN** it completes, and each segment's window equals the window chosen with `weights.aesthetic = 0`

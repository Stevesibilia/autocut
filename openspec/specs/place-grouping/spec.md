# place-grouping Specification

## Purpose

Place grouping turns GPS and time into the editor's notion of "the same spot on the same outing", so selection can limit how many clips come from one visit regardless of how the pixels look.

## Requirements

### Requirement: Places from GPS

Candidates whose file or telemetry carries a GPS position SHALL be grouped into places by single linkage: two candidates within `selection.place_radius_m` (default 150) of each other share a place, and places grow transitively. Each place SHALL receive a stable `place_id` ordered by the earliest shot in it. Candidates without a position MUST have no place and MUST NOT be affected by place caps.

#### Scenario: One beach

- **WHEN** five drone files were shot within 120 m of each other
- **THEN** all five candidates share one `place_id`

#### Scenario: Two coves

- **WHEN** two groups of files are 800 m apart with the default radius
- **THEN** they form two places

#### Scenario: Phone without GPS

- **WHEN** a candidate's file has no GPS tag and no telemetry
- **THEN** its `place_id` is null

### Requirement: Visits within a place

Within a place, candidates SHALL be ordered by absolute time and split into visits wherever the gap between consecutive candidates exceeds `selection.place_visit_gap_seconds` (default 7200). Each visit SHALL receive a `visit_id` unique within the manifest.

#### Scenario: Same beach two days

- **WHEN** a place has shots at 12:25 to 12:36 on day one and 09:10 on day three
- **THEN** it has two visits

#### Scenario: Eleven minutes

- **WHEN** five shots at one place span eleven minutes
- **THEN** they form one visit

### Requirement: Position source

The position of a candidate SHALL be the telemetry position nearest its best window center when telemetry carries GPS, otherwise the file's GPS tag.

#### Scenario: Drone with telemetry

- **WHEN** a drone candidate's file has telemetry with per-second GPS
- **THEN** its place uses the sample nearest the window center, not the file tag

### Requirement: Recorded and reported

`place_id` and `visit_id` SHALL be stored on every candidate and selected segment, the selection block SHALL record the number of places and visits, and `autocut select` SHALL print both.

#### Scenario: Summary line

- **WHEN** selection completes on a folder with 9 places and 12 visits
- **THEN** the CLI prints 9 places and 12 visits

# segmentation Specification

## Purpose

Segmentation splits each file into shot segments and trims the unusable head and tail of each file so that later stages treat each shot as one candidate.

## Requirements

### Requirement: Shot detection

The system SHALL split a file into segments at content changes detected on the sampled frames or on a dedicated detector pass, so that a file with several distinct shots yields several segments. A file with one continuous shot MUST yield exactly one segment.

#### Scenario: Three shots

- **WHEN** a file concatenates three visually different sources of three seconds each
- **THEN** three segments are produced with boundaries within 0.5 seconds of 3.0 and 6.0

#### Scenario: Continuous shot

- **WHEN** a file is one continuous pan
- **THEN** exactly one segment spanning the trimmed file is produced

### Requirement: Telemetry driven split

The system SHALL split each detected shot at the points where telemetry height crosses `rules.drone.min_height_m`, before head and tail trimming, for files whose telemetry carries height. Boundaries SHALL be taken from telemetry sample times snapped to the frame sampling grid. Portions that stay below the threshold SHALL become their own segments and portions above SHALL be left as they are, at both ends of the shot and in the middle. Segments produced by a split SHALL record the reason they were cut out of their shot. Files without height telemetry MUST NOT be affected.

#### Scenario: Takeoff inside a continuous shot

- **WHEN** a six second drone file is one continuous shot with per-second heights 0.5, 1.0, 3.0, 25, 30 and 2.0 and the threshold is 5
- **THEN** three segments are produced, spanning 0.0 to 3.0, 3.0 to 5.0 and 5.0 to 6.0, each recording `altitude` as its split reason

#### Scenario: Flight that never goes low

- **WHEN** every height sample of a shot is above the threshold
- **THEN** the shot yields exactly one segment with no split reason

#### Scenario: Dip in the middle of a flight

- **WHEN** a shot climbs, descends below the threshold and climbs again
- **THEN** three segments are produced and the middle one covers the low portion

#### Scenario: File without height telemetry

- **WHEN** a file has no telemetry or telemetry without height
- **THEN** its shots are not split and no segment records a split reason

### Requirement: Head and tail trim per class

The system SHALL trim the first and last seconds of each file according to the class specific `analysis.head_trim_seconds` and `analysis.tail_trim_seconds`, and SHALL record the trimmed bounds on the segments touching the file edges.

#### Scenario: Phone clip trim

- **WHEN** a 2.0 second `phone` file is analyzed with head and tail trim of 0.3
- **THEN** its single segment spans 0.3 to 1.7 seconds

### Requirement: Minimum segment duration

Segments shorter than `selection.min_segment_seconds` after trimming SHALL be rejected with reason `too_short` and MUST remain in the manifest for the report.

#### Scenario: Short segment

- **WHEN** a segment lasts 1.0 seconds after trimming and the minimum is 1.5
- **THEN** the segment outcome is `rejected` with reason `too_short`

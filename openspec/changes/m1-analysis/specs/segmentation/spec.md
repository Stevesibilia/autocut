## Purpose

Segmentation splits each file into shot segments and trims the unusable head and tail of each file so that later stages treat each shot as one candidate.

## ADDED Requirements

### Requirement: Shot detection

The system SHALL split a file into segments at content changes detected on the sampled frames or on a dedicated detector pass, so that a file with several distinct shots yields several segments. A file with one continuous shot MUST yield exactly one segment.

#### Scenario: Three shots

- **WHEN** a file concatenates three visually different sources of three seconds each
- **THEN** three segments are produced with boundaries within 0.5 seconds of 3.0 and 6.0

#### Scenario: Continuous shot

- **WHEN** a file is one continuous pan
- **THEN** exactly one segment spanning the trimmed file is produced

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

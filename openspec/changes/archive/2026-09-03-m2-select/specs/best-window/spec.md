## Purpose

Best window search finds, inside each candidate segment, the sub-window of target duration that scores highest, and records its center so later stages can grow or shrink the clip around it.

## ADDED Requirements

### Requirement: Highest scoring sub-window

For each candidate segment the system SHALL compute a per-frame composite score from the cached per-frame metrics using the configured weights and the same per-class normalization as the segment score, then find the window of `selection.target_duration_seconds` with the highest mean per-frame score, sliding on the frame sampling grid. The system SHALL store the window center as `best_center_s` and the target duration as `target_duration_s`. A segment shorter than the target duration SHALL use its whole trimmed span and store its midpoint.

#### Scenario: Sharp middle

- **WHEN** a 10 second candidate is blurred for its first 6 seconds and sharp after, with a 3 second target
- **THEN** the best window center lies between 7.5 and 8.5 seconds

#### Scenario: Short candidate

- **WHEN** a candidate lasts 2 seconds and the target is 3 seconds
- **THEN** `best_center_s` is the midpoint of the trimmed span and `target_duration_s` is 2.0

### Requirement: Window stays inside the trimmed span

The chosen window MUST lie entirely within the trimmed bounds of the segment.

#### Scenario: Edge candidate

- **WHEN** the highest scoring frames are the last frames of the segment
- **THEN** the window ends exactly at the trimmed end and its center is half the target duration before it

### Requirement: No decoding

Best window search SHALL run from cached arrays only and MUST NOT decode video.

#### Scenario: Select after analyze

- **WHEN** `autocut select` runs on an analyzed project
- **THEN** no ffmpeg process is started

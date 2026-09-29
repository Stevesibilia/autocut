# best-window Specification

## Purpose

Best window search finds, inside each candidate segment, the sub-window of target duration that scores highest, and records its center so later stages can grow or shrink the clip around it.

## Requirements

### Requirement: Highest scoring sub-window

For each candidate segment the system SHALL compute a per-frame composite score from the cached per-frame metrics using the configured weights and the same per-class normalization as the segment score, then find the window of the candidate's own target duration (assigned by clip durations, or `selection.target_duration_seconds` when none is assigned) with the highest mean per-frame score, sliding on the frame sampling grid. The system SHALL store the window center as `best_center_s` and the duration used as `target_duration_s`. A segment shorter than the target duration SHALL use its whole trimmed span and store its midpoint.

#### Scenario: Sharp middle

- **WHEN** a 10 second candidate is blurred for its first 6 seconds and sharp after, with a 3 second target
- **THEN** the best window center lies between 7.5 and 8.5 seconds

#### Scenario: Short candidate

- **WHEN** a candidate lasts 2 seconds and the target is 3 seconds
- **THEN** `best_center_s` is the midpoint of the trimmed span and `target_duration_s` is 2.0

#### Scenario: Per-clip duration

- **WHEN** a drone clip is assigned 4.8 s and an action cam clip 1.6 s
- **THEN** each window is searched at its own duration and `target_duration_s` differs between them

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

### Requirement: Snap to motion boundary

When `selection.snap_to_motion` is true (default), after the best window is found the system SHALL look for a local minimum of the per-frame motion series within `selection.snap_window_seconds` (default 0.5) before or after the window start, and move the window to start there when the window still fits inside the trimmed span and its mean score drops by no more than 5 percent. The snap SHALL be recorded on the segment.

#### Scenario: Pan begins

- **WHEN** the best window starts 0.3 s into a pan and the motion series has a minimum 0.3 s earlier
- **THEN** the window starts at that minimum and the segment records the snap

#### Scenario: Snap would cost quality

- **WHEN** the nearest motion minimum lowers the window's mean score by 12 percent
- **THEN** the window is not moved

### Requirement: Segment-only metrics do not shape the window

A scored metric that has no per-frame array, such as `aesthetic`, SHALL be left out of the per-frame window score, whatever its weight, and SHALL still count in the segment's composite score.

#### Scenario: Aesthetic weighted

- **WHEN** selection runs with `weights.aesthetic = 1.0`
- **THEN** it completes, and each segment's window equals the window chosen with `weights.aesthetic = 0`

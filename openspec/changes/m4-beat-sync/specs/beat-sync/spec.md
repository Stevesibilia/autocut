## Purpose

Beat sync makes every clip last a whole number of beats of the actual track, so the clips placed back to back fall on the music.

## ADDED Requirements

### Requirement: Track measurement

Given an audio file, the system SHALL decode it to mono WAV through ffmpeg, measure BPM and beat positions, and store them on the manifest soundtrack block. When `--bpm` is given it SHALL be used instead of the measured value and recorded as an override.

#### Scenario: Known track

- **WHEN** a synthetic click track at 120 BPM is provided
- **THEN** the measured BPM is within 1 of 120 and beat positions are 0.5 s apart within 20 ms

#### Scenario: Override

- **WHEN** `--bpm 124` is passed
- **THEN** 124 is used for quantization and the manifest records the override and the measured value

### Requirement: BPM comparison

When a proposed BPM exists, the system SHALL compare it to the effective BPM and warn when they differ by more than `soundtrack.bpm_tolerance`, and SHALL detect the half and double tempo cases (measured near half or twice the proposed) and say so.

#### Scenario: Suno drifted

- **WHEN** the proposed BPM is 120 and the measured is 126 with tolerance 3
- **THEN** a warning names both values

#### Scenario: Half tempo

- **WHEN** the proposed BPM is 120 and the measured is 60
- **THEN** the warning says the track measures at half tempo and offers `--bpm 120`

### Requirement: Quantization to beats

For every selected clip the system SHALL round the assigned target duration to the nearest whole number of beats among `soundtrack.beat_multiples`, hero clips rounding up on ties and others down, then clamp to the trimmed span and fall back to the next smaller multiple when the span is too short. The result SHALL be stored as final bounds centered on the best window center, snapped to the sampling grid, inside the trimmed span. `duration_reason` gains `beat`.

#### Scenario: Two point two seconds at 120

- **WHEN** a clip has target 2.2 s at 120 BPM with multiples 2, 4, 8
- **THEN** its final duration is 2.0 s (four beats)

#### Scenario: Hero tie

- **WHEN** a hero clip has target 3.0 s at 120 BPM
- **THEN** its final duration is 4.0 s (eight beats), not 2.0

#### Scenario: Short segment

- **WHEN** a clip's span is 1.6 s and the nearest multiple is 2.0 s
- **THEN** its final duration is 1.0 s (two beats)

### Requirement: Beat map

The system SHALL write `beatmap.txt` with one line per beat time and a second section listing each clip's order, name and cumulative start time in the edit.

#### Scenario: File content

- **WHEN** sync completes on 29 clips
- **THEN** `beatmap.txt` lists the beat times and 29 cumulative clip starts

### Requirement: Command and re-run

`autocut sync <project> --audio <file> [--bpm N]` SHALL be re-runnable and SHALL reset final bounds before recomputing. Running export afterwards SHALL use the final bounds.

#### Scenario: Re-sync with another track

- **WHEN** sync runs twice with tracks at 110 and 124 BPM
- **THEN** the second run's final bounds reflect 124 and export durations change accordingly

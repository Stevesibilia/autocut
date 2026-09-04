## Purpose

Beat sync makes every clip last a whole number of beats of the actual track, so the clips placed back to back fall on the music.

## ADDED Requirements

### Requirement: Track measurement

Given an audio file, the system SHALL decode it to mono WAV through ffmpeg, measure BPM and beat positions, and store them on the manifest soundtrack block. When `--bpm` is given it SHALL be used instead of the measured value and recorded as an override.

The BPM SHALL be derived from the spacing of the beats found rather than from the tracker's own tempo scalar, because it is the beat grid that the clip lengths are rounded onto and the two can disagree.

#### Scenario: Known track

- **WHEN** a synthetic click track at 120 BPM is provided
- **THEN** the measured BPM is within 1 of 120 and beat positions are 0.5 s apart within 20 ms

#### Scenario: The tracker disagrees with itself

- **WHEN** the tracker reports a tempo of 117.5 while the beats it placed sit 0.5 s apart
- **THEN** the measured BPM is the 120 the beats imply

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

A window moved to a bound of the trimmed span SHALL be snapped again, towards the inside of the span, because a bound of the shot is not a sampled instant unless the trim happens to be. When the span is too short to hold the window on any sampled instant, staying inside the shot SHALL win and the segment SHALL record that the grid was out of reach.

A clip whose span cannot hold even the smallest multiple SHALL take its length from the span, and SHALL then carry no beat count and `duration_reason` `clamped`, because its length is the shot's and not the music's.

`soundtrack.beat_multiples` defaults to 2, 4, 6, 8, 12 and 16, which is half a bar to four bars at 4/4. The first version stopped at 8, and measured on the Sardinia edit that left a 6 s hero clip four beats from anything legal at any tempo in range.

#### Scenario: Two point two seconds at 120

- **WHEN** a clip has target 2.2 s at 120 BPM
- **THEN** its final duration is 2.0 s (four beats)

#### Scenario: Hero tie

- **WHEN** a hero clip and an ordinary clip both have target 2.5 s at 120 BPM, exactly between four and six beats
- **THEN** the hero lasts 3.0 s (six beats) and the other 2.0 s (four beats)

#### Scenario: A long hero has somewhere to land

- **WHEN** a hero clip has target 6.0 s at 120 BPM
- **THEN** its final duration is 6.0 s (twelve beats), which the old multiples could not express

#### Scenario: Short segment

- **WHEN** a clip's span is 1.6 s and the nearest multiple is 2.0 s
- **THEN** its final duration is 1.0 s (two beats)

#### Scenario: Not even the smallest multiple fits

- **WHEN** a clip's span is 0.6 s and the smallest multiple is 1.0 s
- **THEN** its final duration is 0.6 s, it carries no beat count, its reason is `clamped` and the report shows no beat label for it

#### Scenario: A trimmed end off the grid

- **WHEN** a clip's window has to move back to end at a trimmed end of 3.3 s with a sampling grid of 0.5 s
- **THEN** the window starts at 1.0 s, which is on the grid and inside the span

#### Scenario: No sampled instant fits

- **WHEN** a two second window has to fit a span from 0.1 s to 2.2 s with a sampling grid of 0.5 s
- **THEN** the window starts at 0.1 s, stays inside the span, and the segment records that the grid was out of reach

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

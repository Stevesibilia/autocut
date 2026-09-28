## ADDED Requirements

### Requirement: Probe once per file

Analysis SHALL take a file's dimensions, rotation, duration, frame rate and streams from what ingest recorded, and SHALL NOT run ffprobe on the file again.

#### Scenario: Analysing an ingested file

- **WHEN** a file ingested in this run is analysed
- **THEN** no ffprobe process runs for it during analysis

### Requirement: One copy of the sampled frames

Analysis SHALL hold at most one full copy of a file's sampled frames. Motion and content differences SHALL be computed between consecutive frames, without stacking every frame in another type. The measured values SHALL equal the previous implementation's within a relative tolerance of 1e-12.

#### Scenario: Long file

- **WHEN** a 10-minute 1080p file is analysed at the default sampling
- **THEN** the worker's peak memory is within a small constant of the size of the sampled frames, and every metric array matches the previous implementation within 1e-12 relative

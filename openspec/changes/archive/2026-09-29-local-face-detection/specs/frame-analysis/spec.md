## ADDED Requirements

### Requirement: Face counts

When `providers.faces` is on, analysis SHALL count faces on every sampled frame with the bundled YuNet model, keeping detections whose score reaches `analysis.face_score_threshold` and whose height reaches `analysis.face_min_height_share` of the frame height. The counts SHALL be stored as the `faces` cache array together with the model id. A segment's `Metrics.faces` SHALL be the `analysis.face_count_percentile` percentile (lower method) of the counts inside its span, and SHALL be absent when face detection is off. `faces` SHALL be a scored metric weighted by `weights.faces`, and SHALL take part in the best-window search.

#### Scenario: Detection off

- **WHEN** a project is analysed with `providers.faces` off
- **THEN** no detector runs, the cache entry has no `faces` array, every segment's `faces` is absent, and scores equal those of a build without face detection

#### Scenario: Turning detection on over an existing cache

- **WHEN** a file whose cache entry has no face counts is analysed with `providers.faces` on
- **THEN** the file is sampled again, and its new entry holds the `faces` array and the current model id

#### Scenario: A face turned away for a moment

- **WHEN** a segment has eight frames and two people are detected on six of them and one on the other two
- **THEN** its `faces` is 2

#### Scenario: Detector failure

- **WHEN** the face detector cannot load or fails on a file
- **THEN** the file is analysed without face counts and the run reports a warning for it

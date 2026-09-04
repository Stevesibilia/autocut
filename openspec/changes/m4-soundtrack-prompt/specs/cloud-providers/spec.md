## MODIFIED Requirements

### Requirement: Data minimization

Each vision request SHALL contain only the segment's 320 px thumbnail as JPEG and the fixed prompt. Each text request SHALL contain only derived signals (durations, energy band, tags, captions, class mix, time of day, place names) and the template prompt. File names, paths, raw GPS coordinates, timestamps, telemetry and any other manifest field MUST NOT be sent in either kind of request.

#### Scenario: Payload audit

- **WHEN** a request body is captured in a test
- **THEN** it contains the image, the prompt and the model id, and no other segment field

#### Scenario: Text payload audit

- **WHEN** a refinement request body is captured in a test
- **THEN** it contains the signals, the template prompt and the model id, and no coordinates, paths or timestamps

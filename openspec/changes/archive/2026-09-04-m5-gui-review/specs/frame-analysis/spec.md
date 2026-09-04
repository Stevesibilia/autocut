## MODIFIED Requirements

### Requirement: Thumbnails

The system SHALL write one JPEG thumbnail per segment, taken from the sampled frame closest to the segment midpoint, into `thumbs/` under the output folder, and record its path on the segment. When `analysis.sprites` is enabled it SHALL also write a horizontal sprite strip of all sampled frames of the segment. A sprite strip for a single segment SHALL also be producible on demand from the cache entry without decoding video, for a GUI that needs it after analysis ran without sprites.

#### Scenario: Thumbnail path

- **WHEN** analysis completes for a segment
- **THEN** the segment's `thumbnail` points to an existing JPEG under `thumbs/`

#### Scenario: Sprite on demand

- **WHEN** the GUI hovers a segment whose sprite is missing
- **THEN** the strip is built from the cached frames and recorded on the segment, with no ffmpeg process started

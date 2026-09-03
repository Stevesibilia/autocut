# frame-analysis Specification

## Purpose

Frame analysis measures the technical quality of every segment from a sparse sample of downscaled frames and produces a composite score and a thumbnail per segment.

## Requirements

### Requirement: Sampled decoding

The system SHALL decode frames at the configured sample rate (default 2 per second) and long side (default 320 px) and MUST NOT decode every frame of the source. When a proxy is attached to the file and proxies are enabled, sampling SHALL read the proxy. Hardware decoding SHALL be requested when `analysis.hwaccel` is `auto` and MUST fall back to software decoding when the hardware path fails, without failing the file.

#### Scenario: Frame count

- **WHEN** a 20 second file is sampled at 2 frames per second
- **THEN** between 39 and 41 frames are produced, each with long side 320 px

#### Scenario: Proxy used

- **WHEN** a file has an attached `.LRF` proxy and proxies are enabled
- **THEN** frames are read from the proxy and the manifest segment records `analyzed_from: proxy`

#### Scenario: Hardware decode unavailable

- **WHEN** hardware decoding fails for a file
- **THEN** the file is re-sampled with software decoding and a warning is recorded

### Requirement: Per-frame metrics

For each sampled frame the system SHALL compute sharpness as the variance of the Laplacian, exposure clipping as the fraction of pixels at 0 or 255 in luminance, motion as the mean absolute difference to the previous frame normalized to 0 to 1, stability as one minus the normalized standard deviation of motion over a rolling window, and colorfulness with the Hasler and Süsstrunk metric. For files of class `actioncam` sharpness SHALL be computed on the central 60 percent of width and height.

#### Scenario: Blur lowers sharpness

- **WHEN** the same synthetic source is analyzed sharp and Gaussian blurred
- **THEN** the blurred segment's mean sharpness is lower than the sharp segment's

#### Scenario: Overexposure detected

- **WHEN** a frame has more than 30 percent of pixels at 255
- **THEN** its exposure clipping fraction is above 0.3

#### Scenario: Static shot

- **WHEN** a segment shows an unchanging picture
- **THEN** its mean motion is below the configured `rules.min_motion`

#### Scenario: Shaky shot

- **WHEN** a segment has rapidly varying frame to frame displacement
- **THEN** its stability is below the configured `rules.min_stability`

### Requirement: Segment aggregation and composite score

The system SHALL aggregate per-frame metrics into per-segment values (mean sharpness, mean clipping fraction, mean motion, mean stability, mean colorfulness) and compute a composite score as the weighted mean of normalized metrics using `weights` from configuration. Normalization SHALL be per project, across all segments analyzed in the run, so scores are comparable within one manifest. Changing weights and re-running MUST NOT require decoding again.

#### Scenario: Weights change

- **WHEN** analysis has run once and the user changes `weights.colorfulness`
- **THEN** re-running analyze recomputes scores from cached metrics without decoding

#### Scenario: Score range

- **WHEN** scores are computed
- **THEN** every segment score is between 0 and 1

### Requirement: Thumbnails

The system SHALL write one JPEG thumbnail per segment, taken from the sampled frame closest to the segment midpoint, into `thumbs/` under the output folder, and record its path on the segment. When `analysis.sprites` is enabled it SHALL also write a horizontal sprite strip of all sampled frames of the segment.

#### Scenario: Thumbnail path

- **WHEN** analysis completes for a segment
- **THEN** the segment's `thumbnail` points to an existing JPEG under `thumbs/`

### Requirement: Progress and cancellation

The system SHALL emit an `analyze` progress event per file and SHALL stop cleanly between files when the progress callback raises a cancellation, leaving the manifest consistent with the files completed so far.

#### Scenario: Cancel midway

- **WHEN** the callback raises cancellation after the third of ten files
- **THEN** the manifest contains segments for three files and no partial file

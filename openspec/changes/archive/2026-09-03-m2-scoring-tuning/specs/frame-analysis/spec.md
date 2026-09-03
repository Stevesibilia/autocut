## MODIFIED Requirements

### Requirement: Segment aggregation and composite score

The system SHALL aggregate per-frame metrics into per-segment values (mean sharpness, mean clipping fraction, mean motion, mean stability, mean colorfulness) and compute a composite score as the weighted mean of normalized metrics using `weights` from configuration. Normalization SHALL be per source class within the project: a segment's metric ranks are computed against the other segments of the same class analyzed in the run, so scores are comparable within one class of one manifest. A class with a single segment gives that segment 0.5. Changing weights and re-running MUST NOT require decoding again.

#### Scenario: Weights change

- **WHEN** analysis has run once and the user changes `weights.colorfulness`
- **THEN** re-running analyze recomputes scores from cached metrics without decoding

#### Scenario: Score range

- **WHEN** scores are computed
- **THEN** every segment score is between 0 and 1

#### Scenario: Proxy analyzed class does not dominate

- **WHEN** a project has action cam segments analyzed from 720p proxies with systematically higher raw sharpness and drone segments analyzed from 4K originals
- **THEN** the best drone segment and the best action cam segment both score near 1 within their class, and neither class occupies every top rank of the project

#### Scenario: Exposure weight default

- **WHEN** configuration does not set `weights.exposure`
- **THEN** the clipping fraction does not contribute to the composite score

# rejection-rules Specification

## Purpose

Rejection rules discard segments that are unusable for deterministic reasons before scoring, recording the reason so the user can audit and override.

## Requirements

### Requirement: Rules run before scoring and record a reason

Every rule SHALL set the segment outcome to `rejected` with a stable machine readable reason string. Rejected segments MUST keep their metrics and MUST remain in the manifest. Rules are evaluated in the order `too_short`, `low_altitude`, `clipped`, `no_motion`, `shaky`, and a segment rejected by several rules records the first reason in that order.

#### Scenario: Reason recorded

- **WHEN** a segment is rejected
- **THEN** its `reason` is one of `too_short`, `low_altitude`, `clipped`, `no_motion`, `shaky`

#### Scenario: Blown out static shot

- **WHEN** a segment has clipping fraction above the threshold and motion below `rules.min_motion`
- **THEN** it is rejected with `clipped`, not `no_motion`

### Requirement: Low altitude rule

For files with telemetry that includes height, a segment whose maximum height over its duration is below `rules.drone.min_height_m` SHALL be rejected with reason `low_altitude`. Files without height telemetry MUST NOT be affected.

#### Scenario: Takeoff segment

- **WHEN** a drone segment covers seconds 0 to 3 where height rises from 0.5 to 3.0 meters and the threshold is 5
- **THEN** the segment is rejected with `low_altitude`

#### Scenario: Cruise segment

- **WHEN** a drone segment has heights between 25 and 30 meters
- **THEN** it is not rejected by the altitude rule

#### Scenario: Takeoff inside a continuous shot

- **WHEN** a drone file is one continuous shot that climbs from 0.5 meters to 30 meters and the threshold is 5
- **THEN** the telemetry driven split has already cut the low portion into its own segment, that segment is rejected with `low_altitude`, and the segment covering the cruise is not rejected

#### Scenario: Height samples on a split boundary

- **WHEN** a split places a boundary on a telemetry sample time
- **THEN** that sample counts towards the segment starting at the boundary and not towards the segment ending there

### Requirement: No motion rule

A segment whose mean motion is below `rules.min_motion` SHALL be rejected with reason `no_motion`.

#### Scenario: Parked drone

- **WHEN** a segment's mean motion is 0.005 and the threshold is 0.02
- **THEN** it is rejected with `no_motion`

### Requirement: Shaky rule

A segment whose stability is below `rules.min_stability` and whose mean motion is at least `rules.shaky_min_motion` SHALL be rejected with reason `shaky`. The former `rules.max_motion` gate is removed.

#### Scenario: Handheld running

- **WHEN** a segment has motion 0.09 and stability 0.2 with `shaky_min_motion` 0.05 and `min_stability` 0.3
- **THEN** it is rejected with `shaky`

#### Scenario: Smooth fast pan

- **WHEN** a segment has motion 0.15 and stability 0.8
- **THEN** it is not rejected by the shaky rule

#### Scenario: Near static jitter

- **WHEN** a segment has motion 0.01 and stability 0.1 with `shaky_min_motion` 0.05
- **THEN** it is not rejected as `shaky`; the `no_motion` rule decides

### Requirement: Exposure rule

A segment whose mean clipping fraction exceeds `rules.max_clipped_fraction` SHALL be rejected with reason `clipped`.

#### Scenario: Blown out sky

- **WHEN** a segment's mean clipping fraction is 0.12 and the threshold is 0.05
- **THEN** it is rejected with `clipped`

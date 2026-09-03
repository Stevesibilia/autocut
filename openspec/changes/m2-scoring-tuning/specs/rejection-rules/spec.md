## MODIFIED Requirements

### Requirement: Rules run before scoring and record a reason

Every rule SHALL set the segment outcome to `rejected` with a stable machine readable reason string. Rejected segments MUST keep their metrics and MUST remain in the manifest. Rules are evaluated in the order `too_short`, `low_altitude`, `clipped`, `no_motion`, `shaky`, and a segment rejected by several rules records the first reason in that order.

#### Scenario: Reason recorded

- **WHEN** a segment is rejected
- **THEN** its `reason` is one of `too_short`, `low_altitude`, `clipped`, `no_motion`, `shaky`

#### Scenario: Blown out static shot

- **WHEN** a segment has clipping fraction above the threshold and motion below `rules.min_motion`
- **THEN** it is rejected with `clipped`, not `no_motion`

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

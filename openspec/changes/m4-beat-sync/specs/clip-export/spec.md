## MODIFIED Requirements

### Requirement: Precise and fast cut modes

In `precise` mode the system SHALL re-encode the clip with the configured codec and CRF so that in and out points are frame exact. In `fast` mode it SHALL stream copy aligned to keyframes and MUST record on the segment that durations are approximate. Precise is the default. The cut window SHALL be the segment's final bounds when beat sync has set them, otherwise the target duration centered on the best window center.

#### Scenario: Exact duration

- **WHEN** a 3.0 second window is exported in precise mode at 25 fps
- **THEN** the output duration is 3.0 seconds within one frame (0.04 s)

#### Scenario: Fast mode flagged

- **WHEN** a clip is exported in fast mode
- **THEN** the manifest segment records `export_mode: fast` and the report shows the approximate duration marker

#### Scenario: Beat bounds win

- **WHEN** a clip has target 2.2 s and final bounds of 2.0 s from beat sync
- **THEN** the exported clip lasts 2.0 s within one frame

## MODIFIED Requirements

### Requirement: Track and beats

The screen SHALL load an audio file, show its waveform with detected beats, the measured BPM, the comparison to the proposed BPM with the drift and half or double tempo messages, a BPM override field, and a preview of the beat multiple distribution and total duration before Apply sync runs beat sync through the worker. After Apply sync a Play with track control SHALL render the montage with the track muxed and play it with the same timeline as the Review screen.

#### Scenario: Drifted track

- **WHEN** a track measures 126 against a proposed 120
- **THEN** the warning shows both, the override field offers 120, and Apply uses the override when set

#### Scenario: Apply

- **WHEN** the user applies sync
- **THEN** final bounds are set, the Review header shows the new total, and the Export screen enables beat mode

#### Scenario: Hear the cuts

- **WHEN** the user presses Play with track after Apply sync
- **THEN** the montage plays with the track and the clip boundaries on the timeline coincide with beats

# gui-soundtrack Specification

## Purpose
The Soundtrack screen carries the music loop: hand the user a prompt they can copy, take back the track they made, and show how the clips will sit on it.
## Requirements
### Requirement: Prompt blocks and variants

The screen SHALL show Title, Description and Structure each with a Copy button, a variant switcher, the matched genre row with its reason, and the proposed BPM. Changing the BPM field or the genre row SHALL regenerate the variants through the core.

#### Scenario: Copy description

- **WHEN** the user clicks Copy on Description
- **THEN** the clipboard holds exactly the Description text

#### Scenario: BPM edit

- **WHEN** the user sets BPM to 124
- **THEN** the variants regenerate with `124 bpm` in Description and the manifest records 124 as proposed

### Requirement: Mood controls

Two controls, calmer to more energetic and cinematic to intimate, SHALL pick instrument and mood alternates within the matched row and regenerate; they MUST NOT change the genre.

#### Scenario: Calmer

- **WHEN** the user moves toward calmer
- **THEN** the Description mood words change and the genre stays

### Requirement: Hand editing with live validation

The blocks SHALL be editable; every keystroke SHALL run the validator and mark each violated rule inline with its line; a valid edited prompt SHALL be stored as the chosen variant with source `user`; an invalid one MUST NOT be stored or copied without a warning.

#### Scenario: Comma in a tag

- **WHEN** the user types `[slow, dark intro]`
- **THEN** that line is marked with the comma rule and Copy on Structure warns

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

### Requirement: Soundtrack work off the UI thread

Generating the prompt SHALL run on the worker thread whenever it calls a hosted provider, and SHALL stay immediate when it does not. A change to the genre or BPM while generation runs SHALL be applied once after it finishes, without an error. Loading a track SHALL decode and measure it on the worker thread. The screen SHALL show the track, its beats and the tempo comparison when the measurement finishes, and SHALL show the reason in the track label when the file cannot be decoded.

#### Scenario: Cloud refinement

- **WHEN** the user generates a prompt with the cloud on and a key stored
- **THEN** the request runs on the worker thread and the window keeps responding until the variants appear

#### Scenario: Loading a track

- **WHEN** the user loads a song
- **THEN** the window keeps responding while it is measured, and the waveform, beats and tempo comparison appear when it is done

#### Scenario: Undecodable track

- **WHEN** the user loads a file that cannot be decoded
- **THEN** the track label shows why, no error dialog appears, and Apply stays disabled


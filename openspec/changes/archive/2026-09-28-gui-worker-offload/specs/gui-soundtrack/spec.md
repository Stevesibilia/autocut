## ADDED Requirements

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

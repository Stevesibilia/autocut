## MODIFIED Requirements

### Requirement: Audio per class

Audio SHALL be removed when `export.remove_audio` is true for the segment's class and kept otherwise. The default is true for every class, so a default export is silent and the soundtrack carries the sound; a user who wants ambience sets the class to false in `autocut.toml`. `--no-audio` removes it for every clip regardless of configuration.

#### Scenario: Silent by default

- **WHEN** a drone clip and a phone clip are exported with defaults
- **THEN** neither output has an audio stream

#### Scenario: Drone silent, phone keeps ambience

- **WHEN** `export.remove_audio.phone` is false
- **THEN** the phone output keeps its audio and the drone output has none

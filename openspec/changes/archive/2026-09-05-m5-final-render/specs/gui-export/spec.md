## MODIFIED Requirements

### Requirement: Options bound to config

The screen SHALL expose target fps (auto or value), maximum resolution, precise or fast mode, codec, audio removal per class, vertical strategy, slow motion per class, LUT file per class, lens correction per class, the rejects folder toggle, and a "Also render the montage with the track" toggle with its fade-out length, bound to the project configuration and written to `autocut.toml`. When the render toggle is on, Export SHALL run the render after the clips and the summary SHALL name the rendered file.

#### Scenario: Keep phone audio

- **WHEN** the user unchecks audio removal for phone
- **THEN** `autocut.toml` records it and the next export keeps phone audio

#### Scenario: Render toggle

- **WHEN** the user turns on the render toggle and exports with a synced track
- **THEN** `montage.mp4` exists next to `_selects/` and the summary shows its duration and size

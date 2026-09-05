# gui-export Specification

## Purpose

The Export screen turns the reviewed, synced edit into the folder that goes to CapCut, with every export option visible and the result one click away.

## Requirements

### Requirement: Options bound to config

The screen SHALL expose target fps (auto or value), maximum resolution, precise or fast mode, codec, audio removal per class, vertical strategy, slow motion per class, LUT file per class, lens correction per class, the rejects folder toggle, and a "Also render the montage with the track" toggle with its fade-out length, bound to the project configuration and written to `autocut.toml`. When the render toggle is on, Export SHALL run the render after the clips and the summary SHALL name the rendered file.

#### Scenario: Keep phone audio

- **WHEN** the user unchecks audio removal for phone
- **THEN** `autocut.toml` records it and the next export keeps phone audio

#### Scenario: Render toggle

- **WHEN** the user turns on the render toggle and exports with a synced track
- **THEN** `montage.mp4` exists next to `_selects/` and the summary shows its duration and size

### Requirement: Run and progress

Export SHALL run through the worker with a progress bar per clip, the current clip name, skipped and failed counts, and cancel between clips. On completion the screen SHALL show clip count, total duration, folder size, target fps chosen, slow motion and converted counts, and a button that opens the output folder in the OS file manager.

#### Scenario: Second export

- **WHEN** export runs again without changes
- **THEN** every clip is reported skipped and the summary matches the previous run

#### Scenario: One failure

- **WHEN** one clip fails
- **THEN** the run completes, the failed clip is listed with its error, and the others are in the folder

### Requirement: Stale outputs

The screen SHALL show how many stale files were moved to `_selects/_stale/` and offer to delete them.

#### Scenario: After a re-selection

- **WHEN** three clips were dropped since the last export
- **THEN** the summary reports three stale files moved and offers deletion

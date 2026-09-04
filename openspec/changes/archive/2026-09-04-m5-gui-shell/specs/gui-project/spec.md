## Purpose

The Project screen is where a run starts: which folders, where the output goes, which profile, or which existing project to reopen.

## ADDED Requirements

### Requirement: Sources and output

The screen SHALL accept source folders by drag and drop and by a browse dialog, list them with a file count per accepted extension, allow removal, and SHALL require an output folder before analysis can start. It SHALL warn when the output folder already holds a manifest and offer to open it instead.

#### Scenario: Drop a folder

- **WHEN** the user drops a folder with 72 video files
- **THEN** it appears in the list with its count and the Analyze button enables once an output folder is set

#### Scenario: Existing manifest

- **WHEN** the chosen output folder already contains `manifest.json`
- **THEN** the screen offers Open existing or Start over

### Requirement: Profiles

The screen SHALL offer profiles (drone, family, mixed) that preset configuration values (class shares, duration bases, audio removal) and SHALL show which values a profile changed. The user MAY edit any value afterwards in Settings.

#### Scenario: Family profile

- **WHEN** the user picks family
- **THEN** phone audio is kept and the phone class share rises, and the changed values are listed

### Requirement: Open and recent projects

The screen SHALL open a project from any `manifest.json`, restoring its state, and SHALL list the last ten opened projects.

#### Scenario: Reopen

- **WHEN** the user opens a manifest with a completed selection
- **THEN** Review, Soundtrack and Export are enabled and the Review screen shows the selection

### Requirement: Doctor before first run

Before the first analysis in a session the screen SHALL show the doctor report inline, with missing items highlighted, and MUST block only on missing ffmpeg.

#### Scenario: No extra

- **WHEN** the `ai` extra is missing
- **THEN** the report shows embeddings as unavailable and analysis can still start

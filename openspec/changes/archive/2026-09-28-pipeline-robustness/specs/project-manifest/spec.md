## ADDED Requirements

### Requirement: Unreadable manifest reported

A manifest that is not valid JSON or does not validate SHALL be reported by the command line in one line with exit status 1, without a traceback, and the file SHALL be left unchanged.

#### Scenario: Corrupt manifest

- **WHEN** `autocut report` runs on a project whose `manifest.json` is not valid JSON
- **THEN** the command prints one line starting `Cannot open the project`, exits with status 1, and prints no traceback

### Requirement: Backup before migration

When loading a manifest runs at least one migration step, the original file SHALL first be copied next to it as `manifest.v<N>.json.bak`, where `<N>` is the version it was saved with. An existing backup of that name SHALL NOT be overwritten.

#### Scenario: Migrated manifest

- **WHEN** a version 1 manifest is loaded by a build whose schema is 2
- **THEN** `manifest.v1.json.bak` exists next to it and is byte for byte the original

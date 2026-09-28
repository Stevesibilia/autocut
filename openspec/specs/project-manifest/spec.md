# project-manifest Specification

## Purpose

The project manifest is the project file. Loading it checks its schema version and brings an older manifest up to date, so a build never loads a file it cannot represent and writes it back stripped.

## Requirements

### Requirement: Schema version guard

Loading a manifest SHALL read its `schema_version` before validating it. A missing `schema_version` SHALL count as version 1. A manifest whose version is greater than `MANIFEST_SCHEMA_VERSION`, or whose version is not an integer, SHALL be refused with a `ManifestVersionError` that names the file, the version found and the version supported. A refused manifest SHALL NOT be written, so the file on disk is unchanged. The command line SHALL report the refusal as one line and exit with status 1, and the window SHALL show it in a warning dialog and keep the project it had open.

#### Scenario: Newer manifest from the command line

- **WHEN** `autocut report` runs on a project whose `manifest.json` has `schema_version` 2 and this build supports 1
- **THEN** the command prints one line naming both versions, exits with status 1, prints no traceback, and `manifest.json` is byte for byte unchanged

#### Scenario: Newer manifest in the window

- **WHEN** the user picks an output folder whose manifest has a newer schema
- **THEN** a warning dialog names both versions, the project state is unchanged, and no autosave writes the file

#### Scenario: Current manifest

- **WHEN** a manifest with the current `schema_version` is loaded
- **THEN** it loads as before

### Requirement: Migration on load

Every load SHALL pass the manifest through a migration step that brings an older version up to `MANIFEST_SCHEMA_VERSION` one version at a time, from a table keyed by the version each step migrates from. The loaded manifest SHALL carry the current `schema_version`, so the next save writes the migrated form.

#### Scenario: One step migration

- **WHEN** the supported version is 2, a step from 1 is registered, and a version 1 manifest is loaded
- **THEN** the step runs once and the loaded manifest has `schema_version` 2

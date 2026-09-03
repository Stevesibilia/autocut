## MODIFIED Requirements

### Requirement: Manifest written by analyze

The `autocut analyze` command SHALL write `manifest.json` in the output folder with every scanned file, its probe results, proxy, telemetry kind, class and cache key, and SHALL then run segmentation, analysis and rejection rules for every successfully probed file, writing the resulting segments with metrics, scores, outcomes and thumbnails into the same manifest. The command SHALL exit with status 0 when at least one file was probed successfully. When no accepted files are found the command SHALL exit with a non-zero status and a clear message. The manifest MUST be written after ingest and again after analysis so an interrupted run leaves a usable file list.

#### Scenario: Successful ingest

- **WHEN** `autocut analyze ./footage --out ./edit` runs on a folder with accepted files
- **THEN** `./edit/manifest.json` exists, validates against the manifest schema, lists every file and contains at least one segment with a score for every file that was probed successfully

#### Scenario: Empty folder

- **WHEN** the source folder has no accepted files
- **THEN** the command exits non-zero and prints that no video files were found

#### Scenario: Interrupted analysis

- **WHEN** analysis is interrupted after ingest completed
- **THEN** `manifest.json` exists with every file and the segments completed so far

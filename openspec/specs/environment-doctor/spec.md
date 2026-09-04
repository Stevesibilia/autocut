# environment-doctor Specification

## Purpose

The doctor command tells the user what this machine can and cannot do for AutoCut before a long run, so a missing extra, binary or key is discovered in a second rather than after thirty minutes.

## Requirements

### Requirement: Doctor report

`autocut doctor` SHALL print, one line each with an OK or MISSING marker: ffmpeg and ffprobe versions, the hardware decoder that `auto` would choose and whether it verified, whether the `ai` extra imports, the compute device embeddings would use, whether the configured embedding model weights are present, whether a cloud key is available from the environment or the keychain, and the cache directory with its size. It SHALL exit 0 when ffmpeg and ffprobe are present and non-zero otherwise, since nothing works without them.

#### Scenario: Minimal machine

- **WHEN** ffmpeg is present and nothing optional is installed
- **THEN** the report shows ffmpeg OK, extra MISSING, key MISSING, and the exit status is 0

#### Scenario: No ffmpeg

- **WHEN** ffmpeg is not on PATH
- **THEN** the report shows ffmpeg MISSING and the exit status is non-zero

### Requirement: JSON output

`autocut doctor --json` SHALL print the same facts as a JSON object for scripts and the future GUI.

#### Scenario: Machine readable

- **WHEN** `autocut doctor --json` runs
- **THEN** the output parses as JSON with keys for every line of the text report

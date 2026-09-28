## ADDED Requirements

### Requirement: Tool preflight

Before starting any worker, ingest SHALL check that `ffprobe` and `ffmpeg` are on PATH, and export SHALL check that `ffmpeg` is. A missing tool SHALL fail the command once with a message naming it and suggesting `autocut doctor`, not once per file. The command line SHALL report it in one line with exit status 1.

#### Scenario: ffprobe missing

- **WHEN** `autocut analyze` runs on a folder with video files and `ffprobe` is not on PATH
- **THEN** the command prints one line naming `ffprobe`, exits with status 1, and prints no traceback

### Requirement: Failure isolation during ingest

An exception raised while ingesting one file SHALL be recorded as that file's error and SHALL NOT stop the ingest of the other files.

#### Scenario: One worker raises

- **WHEN** ingesting three files and the worker for one raises an unexpected exception
- **THEN** that file is in the result with an error and the other two are ingested

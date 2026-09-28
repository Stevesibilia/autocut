## ADDED Requirements

### Requirement: No partial clip after a failure

A clip whose encode fails for any reason, including a timeout, SHALL leave no file at its output path, so that a later run cannot mistake it for a finished clip. An exception raised while exporting one clip SHALL be recorded as that clip's failure and SHALL NOT stop the other clips.

#### Scenario: Encode times out

- **WHEN** ffmpeg times out after writing part of a clip
- **THEN** the clip's output file does not exist and the clip is recorded as failed

#### Scenario: One worker raises

- **WHEN** the worker for one clip raises an unexpected exception
- **THEN** that clip is recorded as failed and the other clips are exported

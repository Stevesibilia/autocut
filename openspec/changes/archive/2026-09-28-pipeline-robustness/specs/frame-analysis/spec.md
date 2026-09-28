## ADDED Requirements

### Requirement: Failure isolation during analysis

An exception raised while analysing one file SHALL be recorded as that file's error and SHALL NOT stop the analysis of the other files or discard their results. This SHALL hold whether files are analysed in a worker pool or one after another.

#### Scenario: One worker raises

- **WHEN** analysing three files and the worker for the second raises an unexpected exception
- **THEN** the first and third files have segments, the second has an error that starts with `worker failed:`, and the run records one failed file

### Requirement: Interruption keeps finished files

An interrupt from the keyboard during analysis SHALL stop the run the same way a cancellation does: files finished before the interrupt SHALL keep their segments, the run SHALL be recorded as not completed, and the command line SHALL save the manifest and exit with status 130.

#### Scenario: Ctrl-C after the first file

- **WHEN** the user presses Ctrl-C after the first of three files has finished
- **THEN** the manifest is saved with the first file's segments, the run is marked not completed, and the exit status is 130

### Requirement: Sampling never deadlocks on error output

Frame sampling SHALL read the decoder's error output while it reads frames, so that any amount of error output cannot block decoding. At most the last 64 KiB of error output SHALL be kept for the error message.

#### Scenario: Noisy decoder

- **WHEN** the decoder writes 1 MiB of error output before its frames
- **THEN** every frame is read and the call returns

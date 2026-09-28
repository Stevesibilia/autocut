# configuration Specification

## Purpose
TBD - created by archiving change pipeline-robustness. Update Purpose after archive.
## Requirements
### Requirement: Strict configuration

Loading `autocut.toml` SHALL reject any key that no configuration field declares, at any level, and SHALL reject values outside their allowed range: `analysis.sample_fps` greater than zero, `analysis.workers` at least one when set, and `analysis.sprite_max_frames` at least one. The shipped `autocut.example.toml` SHALL load.

#### Scenario: Misspelled key

- **WHEN** `autocut.toml` contains `[analysis] sample_fsp = 3`
- **THEN** loading fails with an error that names the key

#### Scenario: Example file

- **WHEN** `autocut.example.toml` is loaded
- **THEN** it loads without error

### Requirement: Configuration errors on the command line

When `--config` names a file that does not exist, the command SHALL fail with one line starting `Configuration not found` and exit status 1. A configuration file that cannot be read, is not valid TOML or does not validate SHALL fail with one line starting `Cannot read the configuration` and exit status 1, without a traceback. When no `--config` is given and `autocut.toml` does not exist, the defaults SHALL be used as before.

#### Scenario: Missing explicit path

- **WHEN** a command runs with `--config typo.toml` and that file does not exist
- **THEN** it prints `Configuration not found` with the path and exits with status 1


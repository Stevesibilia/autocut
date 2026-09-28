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

### Requirement: Every tunable in configuration

Every threshold, weight and timeout the pipeline uses SHALL be a configuration field with a default. Configuration SHALL include `analysis.high_fps_threshold`, `analysis.fallback_fps`, `similarity.histogram_bins`, `similarity.hash_share`, `export.workers`, and a `[timeouts]` section with `ffprobe_s`, `hwaccel_probe_s`, `sample_read_s`, `export_clip_s`, `montage_part_s`, `concat_s`, `audio_decode_s`, `telemetry_extract_s` and `version_check_s`. Each default SHALL equal the value the code used before it became configurable, so a configuration file written earlier behaves the same.

#### Scenario: Timeout from configuration

- **WHEN** `autocut.toml` sets `[timeouts] ffprobe_s = 5`
- **THEN** probing a file during ingest gives up after 5 seconds

#### Scenario: Defaults unchanged

- **WHEN** no configuration file is present
- **THEN** every threshold and timeout has the value it had before this change


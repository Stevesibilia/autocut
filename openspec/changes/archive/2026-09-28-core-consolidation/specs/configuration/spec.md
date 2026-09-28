## ADDED Requirements

### Requirement: Every tunable in configuration

Every threshold, weight and timeout the pipeline uses SHALL be a configuration field with a default. Configuration SHALL include `analysis.high_fps_threshold`, `analysis.fallback_fps`, `similarity.histogram_bins`, `similarity.hash_share`, `export.workers`, and a `[timeouts]` section with `ffprobe_s`, `hwaccel_probe_s`, `sample_read_s`, `export_clip_s`, `montage_part_s`, `concat_s`, `audio_decode_s`, `telemetry_extract_s` and `version_check_s`. Each default SHALL equal the value the code used before it became configurable, so a configuration file written earlier behaves the same.

#### Scenario: Timeout from configuration

- **WHEN** `autocut.toml` sets `[timeouts] ffprobe_s = 5`
- **THEN** probing a file during ingest gives up after 5 seconds

#### Scenario: Defaults unchanged

- **WHEN** no configuration file is present
- **THEN** every threshold and timeout has the value it had before this change

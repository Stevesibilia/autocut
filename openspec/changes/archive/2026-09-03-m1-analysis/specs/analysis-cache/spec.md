## Purpose

The analysis cache stores decoded metrics and telemetry per source file outside any project, so that re-running analysis or changing weights never decodes video again.

## ADDED Requirements

### Requirement: Global cache location

The cache SHALL live in the platform user cache directory under `autocut/` unless `cache.dir` is configured. The directory MUST be created on first use.

#### Scenario: Default location on Linux

- **WHEN** no `cache.dir` is configured on Linux
- **THEN** entries are written under `~/.cache/autocut/`

### Requirement: Entry key and invalidation

Each entry SHALL be keyed on the file cache key combined with the analysis schema version and the sampling parameters (sample rate, long side). An entry with a different schema version or sampling parameters MUST be treated as missing.

#### Scenario: Cache hit

- **WHEN** a file with an existing entry for the current schema and sampling parameters is analyzed
- **THEN** no decoding happens and metrics are loaded from the entry

#### Scenario: Sampling changed

- **WHEN** `analysis.sample_fps` changes from 2 to 4
- **THEN** the file is decoded again and a new entry is written

### Requirement: Entry content

An entry SHALL contain per-frame metric arrays, frame timestamps, segment boundaries from shot detection, telemetry samples, the probe result, and the source of frames (proxy or original). Thumbnails are stored in the project, not in the cache.

#### Scenario: Round trip

- **WHEN** an entry is written and read back
- **THEN** metric arrays are equal and the probe result validates

### Requirement: Cache inspection

The `autocut cache` command SHALL report the cache directory, entry count and total size, and `autocut cache prune` SHALL delete entries older than a given number of days.

#### Scenario: Cache size

- **WHEN** `autocut cache` runs
- **THEN** it prints the directory, the number of entries and the total size in megabytes

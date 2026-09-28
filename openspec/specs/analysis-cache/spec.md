# analysis-cache Specification

## Purpose

The analysis cache stores decoded metrics and telemetry per source file outside any project, so that re-running analysis or changing weights never decodes video again.
## Requirements
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

### Requirement: Unreadable entries are misses

A cache entry that cannot be read for any reason, including a truncated or corrupt arrays file, SHALL be treated as missing and recomputed. An entry whose metadata names another file key SHALL be treated as missing. An entry whose arrays and metadata were not written together, as shown by a write token stored in both, SHALL be treated as missing; an entry that carries no token in either file SHALL still be read, so entries written before tokens existed stay valid.

#### Scenario: Truncated arrays

- **WHEN** an entry's arrays file is truncated
- **THEN** reading the entry returns nothing and the next analysis recomputes the file without an error

#### Scenario: Arrays and metadata from different writes

- **WHEN** an entry's arrays file and metadata file carry different write tokens
- **THEN** reading the entry returns nothing

### Requirement: Pruning removes orphans

Pruning SHALL also remove, when older than the cutoff, metadata files without an arrays file and leftover temporary files. The count it reports SHALL remain the number of entries removed.

#### Scenario: Orphaned metadata

- **WHEN** the cache holds an old metadata file with no arrays file and an old temporary file
- **THEN** pruning removes both and they are not counted as entries


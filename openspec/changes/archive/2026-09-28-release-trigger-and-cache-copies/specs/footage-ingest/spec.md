## MODIFIED Requirements

### Requirement: Cache key per file

The system SHALL compute for each file a cache key derived from file size, modification time, and a hash of the first and last megabyte of content. The key MUST be identical for two byte-identical copies of a file with the same size and mtime at different paths, and MUST differ when the content of the first or last megabyte differs. The path SHALL NOT be part of the key. A copy that does not preserve the modification time SHALL receive a different key and be analyzed again; this is accepted (ADR 6) because the key is also the file's id in the manifest.

#### Scenario: Copied file

- **WHEN** a file is copied with size and mtime preserved to another folder
- **THEN** both copies receive the same cache key

#### Scenario: Copy without the mtime

- **WHEN** a file is copied to another folder without preserving its mtime
- **THEN** the copy receives a different cache key

#### Scenario: Different content

- **WHEN** two files have equal size and mtime but different first megabyte
- **THEN** their cache keys differ

## ADDED Requirements

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

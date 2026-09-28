## ADDED Requirements

### Requirement: Cached entries for re-selection

Selection SHALL keep up to `cache.memory_entries` recently read analysis cache entries in memory. An entry SHALL be read from disk again only when its files changed or it was evicted. Cached entries SHALL be read-only, and the visual hashes derived from their thumbnails SHALL be computed once per entry. A value of 0 SHALL disable the cache.

#### Scenario: Repeated re-selection

- **WHEN** selection runs ten times in a row on an unchanged project
- **THEN** each cache entry is read from disk once, and the selection result is the same each time

#### Scenario: Re-analysed file

- **WHEN** a file's cache entry is rewritten between two selections
- **THEN** the second selection reads the new entry

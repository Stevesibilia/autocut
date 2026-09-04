## Purpose

Place names turn GPS places into words the soundtrack prompt and the report can use, through online reverse geocoding used sparingly and cached.

## ADDED Requirements

### Requirement: One lookup per place

When `places.geocode` is true (default) and the network is available, the system SHALL reverse geocode the centroid of each place once, store the result under the cache directory keyed by rounded coordinates, and reuse it forever. Requests SHALL carry the project user agent and SHALL be spaced at least one second apart.

#### Scenario: Six places

- **WHEN** the manifest has six places and no cache
- **THEN** six requests are made over at least five seconds and the names are stored

#### Scenario: Cached

- **WHEN** the same places are geocoded again
- **THEN** no request is made

### Requirement: Names in the manifest and report

Each place SHALL record a short name (locality or natural feature) and a region, shown in the report header place list and used by the soundtrack signals.

#### Scenario: Beach name

- **WHEN** a place centroid lies on a named beach
- **THEN** the place name is that beach and the region is its municipality or island

### Requirement: Offline and opt-out

When the network is unavailable or `places.geocode` is false, places keep numeric ids and the prompt omits place names, with one warning.

#### Scenario: Offline

- **WHEN** the geocoder is unreachable
- **THEN** the run completes, no place has a name, and one warning is recorded

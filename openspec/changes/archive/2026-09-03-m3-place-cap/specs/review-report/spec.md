## MODIFIED Requirements

### Requirement: Summary header

The page SHALL show file count per class, segment count per outcome and per reason, total analyzed duration, the number of files served from cache, and the list of places with their visit count and selected clip count.

#### Scenario: Header counts

- **WHEN** the manifest has 10 files with 3 drone, 5 actioncam and 2 phone
- **THEN** the header shows those three counts

#### Scenario: Places listed

- **WHEN** the manifest has 9 places
- **THEN** the header lists nine places, each with its visits and selected clips

## ADDED Requirements

### Requirement: Place on the card and place filter

Each card SHALL show the segment's place and visit when present, candidates held back by the place cap SHALL show reason `place_cap` and the clips that filled the visit, and the page SHALL offer a filter by place.

#### Scenario: Held back card

- **WHEN** a candidate has reason `place_cap` and `held_by` lists three clips
- **THEN** its card shows the reason and the three orders

#### Scenario: Filter by place

- **WHEN** the user selects one place
- **THEN** only segments of that place remain visible and the count updates

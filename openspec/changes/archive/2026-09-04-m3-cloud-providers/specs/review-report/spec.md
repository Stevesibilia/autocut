## MODIFIED Requirements

### Requirement: Summary header

The page SHALL show file count per class, segment count per outcome and per reason, total analyzed duration, the number of files served from cache, the list of places with their visit count and selected clip count, and, when cloud descriptions ran, the model used, the request count and the cost in USD.

#### Scenario: Header counts

- **WHEN** the manifest has 10 files with 3 drone, 5 actioncam and 2 phone
- **THEN** the header shows those three counts

#### Scenario: Places listed

- **WHEN** the manifest has 9 places
- **THEN** the header lists nine places, each with its visits and selected clips

#### Scenario: Cloud cost shown

- **WHEN** the run made 60 cloud requests costing 0.0312 USD
- **THEN** the header shows the model, 60 requests and 0.0312 USD

#### Scenario: No descriptions, no panel

- **WHEN** no cloud description ran
- **THEN** the header shows no description panel at all

## ADDED Requirements

### Requirement: Description on the card

Each card SHALL show the caption when present, cloud tags distinguished from local tags, and the aesthetic value when present.

#### Scenario: Described card

- **WHEN** a segment has a caption and aesthetic 7
- **THEN** its card shows the caption text and the value 7

#### Scenario: Cloud tag distinguished

- **WHEN** a segment carries a cloud tag and a local tag
- **THEN** its card shows the cloud tag first, styled apart from the local one

#### Scenario: A description that failed

- **WHEN** a segment has no caption and a recorded description failure
- **THEN** its card says why it has no description

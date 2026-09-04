# review-report Specification

## Purpose

The review report is a self contained HTML page that lets the user inspect every analyzed segment, its score, metrics and rejection reason, and tune configuration by eye before selection exists.

## Requirements

### Requirement: Self contained page

The report SHALL be a single `report.html` file in the output folder that opens from disk in a browser with no network access and no external assets other than the thumbnails under `thumbs/`, referenced by relative path.

#### Scenario: Offline open

- **WHEN** the output folder is copied to another machine and `report.html` is opened from disk
- **THEN** all thumbnails, sorting and filtering work without network

### Requirement: One card per segment

Each segment in the manifest SHALL appear as a card showing thumbnail, source file name, class and deciding signal, start and end time, duration, composite score, each per-metric value, tags with their confidence and their group, outcome and rejection reason when rejected. Selected segments SHALL show their order, best window, target duration and the reason for that duration, and SHALL be listed first when sorting by chronology. Candidates that lost to a near duplicate SHALL show which selected segment they lost to. Rejected segments MUST be visually distinct from candidates and selected segments from both.

#### Scenario: Rejected card

- **WHEN** a segment has outcome `rejected` with reason `low_altitude`
- **THEN** its card shows the reason and is styled as rejected

#### Scenario: Selected card

- **WHEN** a segment has outcome `selected` with order 12
- **THEN** its card shows `012`, the best window bounds and is styled as selected

#### Scenario: Lost duplicate

- **WHEN** a candidate has `lost_to` set
- **THEN** its card names the selected segment it lost to and its cluster

#### Scenario: Duration reason

- **WHEN** a selected segment has target duration 4.8 s with reason `hero`
- **THEN** its card shows `4.8 s` and `hero`

#### Scenario: Tagged card

- **WHEN** a segment has tags `beach` 0.62 and `people` 0.21
- **THEN** its card shows both tags with their confidence, dominant first

#### Scenario: Secondary tag marked

- **WHEN** a segment carries `beach` from the subject group and `aerial` from the view group
- **THEN** its card shows the subject tag first and marks it as the one that names the clip

### Requirement: Sorting and filtering

The page SHALL offer sorting by chronological order and by score, and filtering by class, by outcome, by rejection reason and by tag, all working client side.

#### Scenario: Filter by reason

- **WHEN** the user selects reason `shaky`
- **THEN** only segments rejected as shaky remain visible and the count updates

#### Scenario: Filter by tag

- **WHEN** the user selects tag `food`
- **THEN** only segments carrying `food` remain visible and the count updates

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

### Requirement: Report command and integration

`autocut report <project>` SHALL render the report from an existing manifest and exit non-zero with a clear message when the manifest is missing. `autocut analyze` SHALL render the report as its last step.

#### Scenario: Missing manifest

- **WHEN** `autocut report ./empty` runs on a folder without `manifest.json`
- **THEN** the command exits non-zero and says the manifest was not found

#### Scenario: Analyze produces report

- **WHEN** `autocut analyze` completes
- **THEN** `report.html` exists next to `manifest.json`

### Requirement: Place on the card and place filter

Each card SHALL show the segment's place and visit when present, candidates held back by the place cap SHALL show reason `place_cap` and the clips that filled the visit, and the page SHALL offer a filter by place.

#### Scenario: Held back card

- **WHEN** a candidate has reason `place_cap` and `held_by` lists three clips
- **THEN** its card shows the reason and the three orders

#### Scenario: Filter by place

- **WHEN** the user selects one place
- **THEN** only segments of that place remain visible and the count updates

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

## Purpose

The review report is a self contained HTML page that lets the user inspect every analyzed segment, its score, metrics and rejection reason, and tune configuration by eye before selection exists.

## ADDED Requirements

### Requirement: Self contained page

The report SHALL be a single `report.html` file in the output folder that opens from disk in a browser with no network access and no external assets other than the thumbnails under `thumbs/`, referenced by relative path.

#### Scenario: Offline open

- **WHEN** the output folder is copied to another machine and `report.html` is opened from disk
- **THEN** all thumbnails, sorting and filtering work without network

### Requirement: One card per segment

Each segment in the manifest SHALL appear as a card showing thumbnail, source file name, class and deciding signal, start and end time, duration, composite score, each per-metric value, outcome and rejection reason when rejected. Rejected segments MUST be visually distinct from candidates.

#### Scenario: Rejected card

- **WHEN** a segment has outcome `rejected` with reason `low_altitude`
- **THEN** its card shows the reason and is styled as rejected

### Requirement: Sorting and filtering

The page SHALL offer sorting by chronological order and by score, and filtering by class, by outcome and by rejection reason, all working client side.

#### Scenario: Filter by reason

- **WHEN** the user selects reason `shaky`
- **THEN** only segments rejected as shaky remain visible and the count updates

### Requirement: Summary header

The page SHALL show file count per class, segment count per outcome and per reason, total analyzed duration and the number of files served from cache.

#### Scenario: Header counts

- **WHEN** the manifest has 10 files with 3 drone, 5 actioncam and 2 phone
- **THEN** the header shows those three counts

### Requirement: Report command and integration

`autocut report <project>` SHALL render the report from an existing manifest and exit non-zero with a clear message when the manifest is missing. `autocut analyze` SHALL render the report as its last step.

#### Scenario: Missing manifest

- **WHEN** `autocut report ./empty` runs on a folder without `manifest.json`
- **THEN** the command exits non-zero and says the manifest was not found

#### Scenario: Analyze produces report

- **WHEN** `autocut analyze` completes
- **THEN** `report.html` exists next to `manifest.json`

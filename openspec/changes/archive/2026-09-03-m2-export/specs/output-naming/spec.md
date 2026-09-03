## Purpose

Output naming carries the chronological order into CapCut, which imports alphabetically, and makes every file self describing.

## ADDED Requirements

### Requirement: File name format

Each exported clip SHALL be named `{index:03d}_{date}_{class}_{tag}_{duration}s.mp4` where index is the selection order, date is the local date of the clip as `YYYYMMDD`, class is the source class, tag is the first semantic tag or `clip` when none, and duration is the output duration with one decimal. Names MUST sort in selection order.

#### Scenario: Example name

- **WHEN** the 12th selected clip is a drone clip from 2026-08-12 lasting 4.0 seconds with no tags
- **THEN** its file is `012_20260812_drone_clip_4.0s.mp4`

#### Scenario: Alphabetical equals chronological

- **WHEN** 45 clips are exported
- **THEN** sorting the file names alphabetically yields the selection order

### Requirement: Folder layout

Exports SHALL go to `_selects/` under the output folder. When `export.keep_rejects` or `--rejects` is set, rejected segments SHALL be exported to `_rejects/` with the same naming and the reason in place of the tag. Existing files in `_selects/` that no longer correspond to a selected segment SHALL be moved to `_selects/_stale/` rather than deleted.

#### Scenario: Reselect

- **WHEN** a clip was exported, then `select` drops it and `export` runs again
- **THEN** its old file is under `_selects/_stale/` and `_selects/` contains only current clips

### Requirement: Report links

The report SHALL show the exported file name on each selected card and link to it relatively.

#### Scenario: Card link

- **WHEN** a selected segment has `exported_path`
- **THEN** its card links to `_selects/<name>`

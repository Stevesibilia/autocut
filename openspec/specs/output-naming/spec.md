# output-naming Specification

## Purpose

Output naming carries the chronological order into CapCut, which imports alphabetically, and makes every file self describing.

## Requirements

### Requirement: File name format

Each exported clip SHALL be named `{index:03d}_{date}_{class}_{tag}_{duration}s.mp4` where index is the selection order, date is the local date of the clip as `YYYYMMDD`, class is the source class, tag is the segment's dominant tag lowercased with spaces replaced by hyphens, or `clip` when the segment has no dominant tag, and duration is the output duration with one decimal. Only a tag from the primary label group can appear here: a view or a lighting tag describes how a shot was taken rather than what it shows, and the class field already carries the former. Names MUST sort in selection order.

#### Scenario: Example name

- **WHEN** the 12th selected clip is a drone clip from 2026-08-12 lasting 4.0 seconds with no tags
- **THEN** its file is `012_20260812_drone_clip_4.0s.mp4`

#### Scenario: Tagged name

- **WHEN** the 13th selected clip is a phone clip from 2026-08-12 lasting 2.0 seconds tagged `people` first
- **THEN** its file is `013_20260812_phone_people_2.0s.mp4`

#### Scenario: A secondary tag does not name a clip

- **WHEN** the 14th selected clip is a drone clip carrying only `aerial`, from the view group
- **THEN** its file is named with `clip` rather than with `aerial`

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

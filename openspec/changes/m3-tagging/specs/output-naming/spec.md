## MODIFIED Requirements

### Requirement: File name format

Each exported clip SHALL be named `{index:03d}_{date}_{class}_{tag}_{duration}s.mp4` where index is the selection order, date is the local date of the clip as `YYYYMMDD`, class is the source class, tag is the segment's dominant tag lowercased with spaces replaced by hyphens, or `clip` when the segment has no tags, and duration is the output duration with one decimal. Names MUST sort in selection order.

#### Scenario: Example name

- **WHEN** the 12th selected clip is a drone clip from 2026-08-12 lasting 4.0 seconds with no tags
- **THEN** its file is `012_20260812_drone_clip_4.0s.mp4`

#### Scenario: Tagged name

- **WHEN** the 13th selected clip is a phone clip from 2026-08-12 lasting 2.0 seconds tagged `people` first
- **THEN** its file is `013_20260812_phone_people_2.0s.mp4`

#### Scenario: Alphabetical equals chronological

- **WHEN** 45 clips are exported
- **THEN** sorting the file names alphabetically yields the selection order

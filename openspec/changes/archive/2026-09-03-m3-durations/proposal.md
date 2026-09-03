## Why

Every exported clip lasts exactly `selection.target_duration_seconds`, 3.0 s on the Sardinia edit. Forty identical durations read as a slideshow: aerials need longer to be read, action shots feel long at 3 s, and nothing in the sequence breathes or accelerates. Editing practice varies shot length with content, gives the best shots more time and alternates long and short. SPEC.md section 7.6 leaves duration variety to beat sync, which needs a track; this change gives the edit rhythm before any music exists and leaves beat sync a better starting point.

## What Changes

- Per-clip target duration decided at selection time from a class base duration scaled by the clip's score, with a hero bonus for the top share of clips, clamped to configured bounds and to the segment's trimmed span.
- Long and short alternation over the chronological order, so no three consecutive clips fall in the same duration bucket when the segments allow it.
- Optional total duration target: when `selection.target_total_seconds` is set, all durations are scaled proportionally within bounds so the edit lands near it.
- Best window search uses the per-clip target duration instead of one project-wide value, and optionally snaps the window start to a motion boundary so the cut lands where movement begins.
- The reason for each clip's duration (`base`, `hero`, `alternation`, `total`, `clamped`) recorded on the segment and shown in the report.
- `autocut select` flags `--duration` keeps working as an override that disables the variety and sets one duration for every clip.

## Capabilities

### New Capabilities

- `clip-durations`: assigning each selected clip its own target duration from class, score, rhythm and total length constraints.

### Modified Capabilities

- `best-window`: the window is searched at the clip's own duration and may snap to a motion boundary.
- `review-report`: the duration reason is shown on selected cards.

## Impact

- New module `autocut/core/durations.py`; `select.py` calls it before window placement; `window.py` gains the motion snap.
- `autocut/core/config.py`: `selection.duration_by_class`, `selection.duration_min_seconds`, `selection.duration_max_seconds`, `selection.score_duration_range`, `selection.hero_share`, `selection.hero_multiplier`, `selection.alternate_durations`, `selection.target_total_seconds`, `selection.snap_to_motion`. The existing `target_duration_seconds` becomes the fallback used when `--duration` is passed or a class has no base.
- `autocut/core/manifest.py`: `Segment.duration_reason`; `Manifest.selection` records the total duration.
- Export and naming need no change: they already read `target_duration_s` per segment.
- Beat sync (M4) will quantize the assigned durations to beat multiples rather than derive them from score; noted for that change's design.
- Independent of the AI changes; ordered before `m3-embeddings` because it changes what the user judges in CapCut.

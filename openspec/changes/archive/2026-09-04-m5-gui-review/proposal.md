## Why

The Review screen is the reason the GUI exists: no scoring gets every pick right, and the fix has to take a click, not a config edit and a rerun. SPEC.md section 11 calls it the central screen. It needs one new core concept, user decisions that survive re-selection, so that a human keep or reject is not undone the next time a slider moves.

## What Changes

- Core: user decisions on segments (`keep`, `reject`, custom in and out) stored in the manifest, honored by selection as pins: kept segments are always selected, rejected ones never, custom bounds override the window. `autocut select` respects them too.
- Thumbnail grid of segments sorted by chronology or score, filtered by class, tag, place, outcome, reason and score range, with a visible counter of selected clips and total duration.
- Hover scrubbing on the segment's sprite strip; `analysis.sprites` turned on by the GUI's analysis run.
- Keep and reject by click and keyboard (space, arrows, K, R), undo.
- Clip preview with in and out adjustment on the original or proxy through `QMediaPlayer`, snapping to the sampling grid.
- Weight sliders that re-score from cache and re-sort the grid live; diversity slider that re-selects live, both debounced.
- Similar groups view: clusters and place visits as stacks with the chosen clip on top, one click to swap the pick.
- Export of the current review as `report.html` so the CLI report stays in sync.

## Capabilities

### New Capabilities

- `user-decisions`: pins and custom bounds that survive re-selection, in core and CLI.
- `gui-review`: the grid, preview, sliders and group view.

### Modified Capabilities

- `clip-selection`: re-runnable select honors user decisions.
- `frame-analysis`: sprite strips generated when requested by the GUI, and generated on demand for a segment when missing.

## Impact

- Core: `Segment.user_decision` (`keep`, `reject`, `none`), `Segment.user_start_s`, `Segment.user_end_s`; `select.py` pins; `analyze.py` on-demand sprite for one segment from the cache; `autocut select` unchanged in interface.
- GUI: `screens/review.py`, `widgets/thumb_grid.py`, `widgets/scrubber.py`, `widgets/preview.py`, `widgets/sliders.py`, `widgets/groups.py`.
- Depends on `m5-gui-shell`.

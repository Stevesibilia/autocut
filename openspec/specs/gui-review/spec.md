# gui-review Specification

## Purpose

The Review screen lets a person correct the machine in two minutes: see every candidate, scrub it, keep or reject it, move the sliders, and swap a duplicate for its neighbour.

## Requirements

### Requirement: Grid, sorting and filters

The screen SHALL show every non-rejected segment as a rounded thumbnail card with: a badge top left reading `IN n` (selected, accent), `KEPT n` (user keep, amber), `OUT` (candidate not selected, muted) or `REJECTED` (user reject, red); duration and, when the edit is synced, the beat count top right; the class and score on one line; tags as chips; place and time of day on the last line, or the reason a candidate lost (`lost to IN 2 · similar 0.81`, a rule name, `rejected by you`) when it is out. A hero clip SHALL carry a `hero` badge. The card of the clip currently playing or focused SHALL have an accent border. Sorting by chronology or score and filtering by class, tag, place, outcome, rejection reason and score range SHALL be offered as a row of chips above the grid, with a toggle to show rejected segments and one to open the similar groups view. The counters live in the top bar of the window and update on every change.

#### Scenario: Filter to a place

- **WHEN** the user picks one place in the Place chip
- **THEN** only its segments show and the top bar counts stay project wide

#### Scenario: Card of a candidate that lost

- **WHEN** a candidate was dropped by the similarity cap
- **THEN** its card is dimmed, reads `OUT`, and names the clip it lost to and the similarity

### Requirement: Hover scrub

Hovering a card SHALL scrub through the segment's sprite strip following the pointer position; when the strip is missing it SHALL be produced on demand from the cache.

#### Scenario: Scrub

- **WHEN** the pointer moves across a card from left to right
- **THEN** the card shows frames from the segment start to its end

### Requirement: Keep and reject

Click controls and keyboard shortcuts (K keep, R reject, space toggle keep, arrows move, U undo) SHALL set user decisions; the grid SHALL reflect the new selection immediately through a re-select from cache; undo SHALL restore the previous decision.

#### Scenario: Reject with the keyboard

- **WHEN** the user presses R on a selected card
- **THEN** the card shows user-rejected, the selection re-runs, and the header count drops by one or another candidate fills the slot

### Requirement: Preview and trim

The right panel SHALL show, top to bottom: the file name with its time of day and length, the preview player with the window marked, the in and out points as a range bar with the values in the mono face, a Play clip button and an Automatic window button, then the Diversity slider with its value and the labels `best only` and `most varied`, then the weight sliders with a reset action, and finally a summary of similar groups (stacks, places, candidates held back by caps). Double clicking a card SHALL focus it in the panel. Dragging in and out points SHALL snap to the sampling grid inside the trimmed span and save as custom bounds. A Play all control in the top bar SHALL render the montage preview when its fingerprint changed and play it; the montage timeline strip SHALL sit under the grid with one block per clip, played blocks in the muted accent, the current block in the accent, upcoming blocks in the surface colour, a line above it naming the clip and file and a mono `elapsed / total` counter, and a row of key hints (`K` keep, `R` reject, `space` toggle, `U` undo, `↵` open clip). Clicking a block SHALL seek there and focus that card, and the keyboard decisions SHALL apply to the clip currently playing. The panel SHALL be collapsible and expandable from a control in the top bar, SHALL start collapsed when the window is narrower than `gui.panel_collapse_width` (default 1280 px), and SHALL remember its state for the session. The panel's content SHALL never be wider than the panel: file names and range labels elide with the full text on a tooltip and value columns size from the font. Stop SHALL be enabled whenever a player exists, playing or paused, and SHALL return the preview to the strip at the in point and clear the note.

#### Scenario: Set bounds

- **WHEN** the user drags the out point to 6.5 s
- **THEN** the segment records user bounds, the range bar and the card show the new duration

#### Scenario: Play all

- **WHEN** the user presses Play all on a 29 clip selection
- **THEN** the montage renders once, playback starts, the strip shows 29 blocks and the accent block and the grid border move together from clip to clip

#### Scenario: Reject while playing

- **WHEN** the user presses R during playback of clip 7
- **THEN** clip 7 is user-rejected, its card turns to `REJECTED`, playback continues, and the montage is marked stale for the next Play all

#### Scenario: Collapsed on a narrow window

- **WHEN** the window opens 1200 px wide
- **THEN** the right panel is collapsed, the grid takes the width, and the top bar control expands it on demand

#### Scenario: Long file name

- **WHEN** the focused clip's file name is sixty characters long
- **THEN** the panel content's minimum width stays within the panel width and the name is elided with a tooltip

#### Scenario: Stop after the out point

- **WHEN** playback pauses at the out point and the user presses Stop
- **THEN** the strip is shown at the in point, the note is empty and Play is enabled

### Requirement: Live sliders

Weight sliders (one per scored metric) SHALL re-score from cache and re-sort the grid; the diversity slider SHALL re-select; both debounced to `gui.slider_debounce_ms` (default 250) and never decoding video. The slider panel SHALL be visible on the screen, not in a settings dialog.

#### Scenario: Diversity to zero

- **WHEN** the user drags diversity to 0
- **THEN** within a second the selection equals pure score ranking under the caps and the header updates

### Requirement: Similar groups

A groups mode SHALL show visual clusters and place visits as stacks with the selected clip on top and the others behind; clicking a hidden one SHALL keep it and reject the current pick in one action.

#### Scenario: Swap pick

- **WHEN** the user clicks the second clip of a cluster stack
- **THEN** it becomes user-kept, the former pick becomes user-rejected, and the stack reorders

### Requirement: Report in sync

The screen SHALL offer Export report, writing `report.html` from the current state so the CLI report reflects the review.

#### Scenario: Report after review

- **WHEN** the user exports the report after rejecting two clips
- **THEN** `report.html` shows them as user-rejected

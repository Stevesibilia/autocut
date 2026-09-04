## Purpose

The Review screen lets a person correct the machine in two minutes: see every candidate, scrub it, keep or reject it, move the sliders, and swap a duplicate for its neighbour.

## ADDED Requirements

### Requirement: Grid, sorting and filters

The screen SHALL show every non-rejected segment as a thumbnail card with class, duration, score, tags, place and outcome markers, sortable by chronology or score, and filterable by class, tag, place, outcome, rejection reason and a score range. A toggle SHALL reveal rejected segments. A header SHALL show the count of selected clips and the total edit duration and update on every change.

#### Scenario: Filter to a place

- **WHEN** the user picks one place
- **THEN** only its segments show and the header counts stay project wide

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

Double clicking a card SHALL open a preview playing the segment from the original or proxy with the window marked, and SHALL allow dragging in and out points snapped to the sampling grid inside the trimmed span, saving them as custom bounds.

#### Scenario: Set bounds

- **WHEN** the user drags the out point to 6.5 s
- **THEN** the segment records user bounds and the card shows the new duration

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

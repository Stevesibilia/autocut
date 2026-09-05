## MODIFIED Requirements

### Requirement: Grid, sorting and filters

The screen SHALL show every non-rejected segment as a rounded thumbnail card with: a badge top left reading `IN n` (selected, accent), `KEPT n` (user keep, amber), `OUT` (candidate not selected, muted) or `REJECTED` (user reject, red); duration and, when the edit is synced, the beat count top right; the class and score on one line; tags as chips; place and time of day on the last line, or the reason a candidate lost (`lost to IN 2 · similar 0.81`, a rule name, `rejected by you`) when it is out. A hero clip SHALL carry a `hero` badge. The card of the clip currently playing or focused SHALL have an accent border. Sorting by chronology or score and filtering by class, tag, place, outcome, rejection reason and score range SHALL be offered as a row of chips above the grid, with a toggle to show rejected segments and one to open the similar groups view. The counters live in the top bar of the window and update on every change.

#### Scenario: Filter to a place

- **WHEN** the user picks one place in the Place chip
- **THEN** only its segments show and the top bar counts stay project wide

#### Scenario: Card of a candidate that lost

- **WHEN** a candidate was dropped by the similarity cap
- **THEN** its card is dimmed, reads `OUT`, and names the clip it lost to and the similarity

### Requirement: Preview and trim

The right panel SHALL show, top to bottom: the file name with its time of day and length, the preview player with the window marked, the in and out points as a range bar with the values in the mono face, a Play clip button and an Automatic window button, then the Diversity slider with its value and the labels `best only` and `most varied`, then the weight sliders with a reset action, and finally a summary of similar groups (stacks, places, candidates held back by caps). Double clicking a card SHALL focus it in the panel. Dragging in and out points SHALL snap to the sampling grid inside the trimmed span and save as custom bounds. A Play all control in the top bar SHALL render the montage preview when its fingerprint changed and play it; the montage timeline strip SHALL sit under the grid with one block per clip, played blocks in the muted accent, the current block in the accent, upcoming blocks in the surface colour, a line above it naming the clip and file and a mono `elapsed / total` counter, and a row of key hints (`K` keep, `R` reject, `space` toggle, `U` undo, `↵` open clip). Clicking a block SHALL seek there and focus that card, and the keyboard decisions SHALL apply to the clip currently playing.

#### Scenario: Set bounds

- **WHEN** the user drags the out point to 6.5 s
- **THEN** the segment records user bounds, the range bar and the card show the new duration

#### Scenario: Play all

- **WHEN** the user presses Play all on a 29 clip selection
- **THEN** the montage renders once, playback starts, the strip shows 29 blocks and the accent block and the grid border move together from clip to clip

#### Scenario: Reject while playing

- **WHEN** the user presses R during playback of clip 7
- **THEN** clip 7 is user-rejected, its card turns to `REJECTED`, playback continues, and the montage is marked stale for the next Play all

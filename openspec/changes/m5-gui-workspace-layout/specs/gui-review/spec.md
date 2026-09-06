## MODIFIED Requirements

### Requirement: Preview and trim

The right panel SHALL show, top to bottom: the file name with its time of day and length, the preview player with the window marked, the in and out points as a range bar with the values in the mono face, a Play clip button and an Automatic window button, then the Diversity slider with its value and the labels `best only` and `most varied`, then the weight sliders with a reset action, and finally a summary of similar groups (stacks, places, candidates held back by caps). Double clicking a card SHALL focus it in the panel. Dragging in and out points SHALL snap to the sampling grid inside the trimmed span and save as custom bounds. A Play all control in the top bar SHALL render the montage preview when its fingerprint changed and play it; the montage timeline strip SHALL sit under the grid with one block per clip, played blocks in the muted accent, the current block in the accent, upcoming blocks in the surface colour, a line above it naming the clip and file and a mono `elapsed / total` counter, and a row of key hints (`K` keep, `R` reject, `space` toggle, `U` undo, `↵` open clip). Clicking a block SHALL seek there and focus that card, and the keyboard decisions SHALL apply to the clip currently playing. The panel SHALL be collapsible and expandable from a control in the top bar, SHALL start collapsed when the window is narrower than `gui.panel_collapse_width` (default 1280 px), and SHALL remember its state for the session. The panel's content SHALL never be wider than the panel: file names and range labels elide with the full text on a tooltip and value columns size from the font. Stop SHALL be enabled whenever a player exists, playing or paused, and SHALL return the preview to the strip at the in point and clear the note. The centre column and the right panel SHALL be separated by a splitter the user drags; the panel SHALL not go under `gui.panel_min_width` (default 280 px) nor leave the grid less than four cards wide, and its position SHALL be remembered per machine. The preview stage SHALL keep a 16:9 aspect locked to the panel width, so a wider panel is a larger preview, and the video widget SHALL NOT impose the footage's native size on the panel: the panel's content height SHALL stay bounded by its controls whatever plays.

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

#### Scenario: First Play

- **WHEN** Play runs for the first time on a 4K clip
- **THEN** the video shows in the 16:9 stage at the panel width and every control under it stays where it was

#### Scenario: Wider panel

- **WHEN** the user drags the splitter so the panel is 600 px wide
- **THEN** the preview is 600 px by 338 px, the grid reflows, and the next start opens with the same split

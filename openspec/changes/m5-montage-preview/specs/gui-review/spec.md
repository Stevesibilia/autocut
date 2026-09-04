## MODIFIED Requirements

### Requirement: Preview and trim

Double clicking a card SHALL open a preview playing the segment from the original or proxy with the window marked, and SHALL allow dragging in and out points snapped to the sampling grid inside the trimmed span, saving them as custom bounds. A Play all control SHALL render the montage preview when its fingerprint changed and play it in a player with a timeline marked at every clip boundary; the card of the clip currently playing SHALL be highlighted in the grid, clicking a boundary SHALL seek there and select that card, and the keyboard decisions (K, R, space, U) SHALL apply to the clip currently playing.

#### Scenario: Set bounds

- **WHEN** the user drags the out point to 6.5 s
- **THEN** the segment records user bounds and the card shows the new duration

#### Scenario: Play all

- **WHEN** the user presses Play all on a 29 clip selection
- **THEN** the montage renders once, playback starts, and the grid highlight moves from card to card as clips change

#### Scenario: Reject while playing

- **WHEN** the user presses R during playback of clip 7
- **THEN** clip 7 is user-rejected, playback continues, and the montage is marked stale for the next Play all

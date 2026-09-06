## Why

Play all replaces the Review grid with the montage player and nothing brings the grid back: `show_grid` exists but no control calls it, so after the montage ends the user is left on "End of the edit." with the tiles gone (found on the Mac, 2026-09-06). The only way back today is toggling Similar groups on and off or reopening the project.

## What Changes

- The montage player SHALL carry a "Back to clips" control, and Escape while the montage has focus SHALL do the same: pause the montage and show the grid, with the clip that was playing selected. Play all in the top bar SHALL become a toggle that reads "Back to clips" while the montage is shown.
- The Play all path SHALL not leave the montage on screen once the edit ends: at the end of the edit the player stays on the last frame with the transport, and the Back to clips control is the way out; nothing else changes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gui-review`: the montage view gains its exit.

## Impact

`autocut/gui/screens/review.py`, `autocut/gui/widgets/montage.py`, `autocut/gui/widgets/topbar.py` (action label). Tests under `tests/unit/test_gui_montage_player.py` and `test_gui_review.py`.

## Context

`ReviewScreen.show_grid` pauses the montage and switches the stack back to the grid, and nothing calls it. The montage player has a transport (Play, From the start, Sound) but no exit; the top bar's Play all only enters.

## Decisions

**Three ways out, one slot.** A `Back to clips` button on the montage transport row, a `QShortcut(Qt.Key_Escape)` scoped to the montage widget, and the top bar action toggling its label between `Play all` and `Back to clips` all call `show_grid`. `show_grid` also selects the clip that was playing (`montage.current_segment_id`) so the reviewer lands on what they were watching.

**No auto exit.** The montage stays on its last frame at the end of the edit; leaving automatically would pull the grid under a user who is reaching for From the start.

## Risks / Trade-offs

Escape on the montage competes with nothing today; if a dialog later uses it, the shortcut is widget scoped.

## Migration Plan

None.

## Open Questions

None.

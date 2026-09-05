## Why

The first run on the MacBook (2026-09-05) found the window larger than the screen and not resizable: the layout's minimum size exceeds a laptop display, so macOS pins the window at that size. The same run found that Play does nothing: the Play buttons connect `clicked(bool)` straight to `play(video_output=None)`, so the player receives `False` as its video output and raises. Both are regressions of `m5-visual-design`, platform independent, seen first on the Mac because the Linux tests run offscreen at whatever size the layout asks for.

## What Changes

- The window SHALL fit and be resizable on a 1440x900 logical display with every screen and a real project loaded, with a minimum window size of 1100x680. Wide rows (filter chips, top bar counters and actions, decision buttons) SHALL shrink or wrap instead of imposing their full width; tall panels SHALL scroll.
- The right panel of the Review screen SHALL be collapsible from the top bar, as the approved design intended, and SHALL start collapsed when the window is narrower than 1280 px.
- Play buttons SHALL call the player without the `clicked` boolean; `play` SHALL reject a non-widget video output with a clear error rather than passing it to Qt.
- An offscreen test SHALL load the synthetic project, show each screen, and assert the window's minimum size hint fits 1100x680 and that the window can be resized to that size; a second test SHALL press each Play button through the widget and assert the player was built with a video widget.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gui-shell`: the window requirement gains the size and resizability contract.
- `gui-review`: the right panel becomes collapsible.

## Impact

`autocut/gui/app.py`, `widgets/topbar.py`, `widgets/chips.py`, `widgets/rail.py`, `screens/review.py` and the other screens where a row or a panel imposes a minimum, `widgets/preview.py` and `widgets/montage.py` for the Play slots, `autocut/gui/theme/tokens.py` for the new metrics (minimum window, collapse threshold). New tests under `tests/unit/`. No core change, no manifest change.

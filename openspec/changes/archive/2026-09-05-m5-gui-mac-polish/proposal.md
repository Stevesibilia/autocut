## Why

The second macOS run (2026-09-05 evening, Retina display, real footage) found three defects the Linux offscreen suite cannot see: rail and button icons render as a corner fragment, the Review right panel's content is wider than the panel and is clipped at the window edge, and Stop is disabled once playback pauses at the out point. A fourth need is diagnostic: the window's size behaviour on the Mac can only be guessed from screenshots, so the application should be able to print what it sees.

## What Changes

- Icons render into the pixmap's logical rectangle, so a device pixel ratio of 2 draws the whole glyph at twice the pixels rather than the top left quarter. A test renders at ratio 2 and asserts paint in the bottom right quadrant.
- The Review right panel's content SHALL never exceed the panel width: long file names and range labels elide with the full text on the tooltip, slider value columns take their width from the font, and a test asserts the content's minimum width against the panel width with a long file name.
- Stop SHALL be enabled whenever a player exists (playing or paused) and SHALL return the preview to the strip and the in point; the note clears. A test presses Stop after the out point pause.
- `autocut gui --diagnose` prints the screens (geometry, available geometry, device pixel ratio), the registered font families, the theme in use and the window's minimum size hint and opening size, then exits. Same output on demand from the Settings dialog is out of scope.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gui-theme`: the HiDPI scenario becomes specific about the whole glyph; a diagnostics scenario joins the theme setting requirement.
- `gui-review`: the panel content fit and the Stop behaviour join the preview requirement.

## Impact

`autocut/gui/theme/icons.py`, `autocut/gui/screens/review.py`, `autocut/gui/widgets/{preview,sliders,topbar}.py`, `autocut/gui/app.py`, `autocut/cli/main.py` for the flag. No core, manifest or config change.

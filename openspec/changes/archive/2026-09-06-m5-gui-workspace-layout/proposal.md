## Why

The third macOS run (2026-09-06) shows the Review right panel exploding into a black column the first time Play is pressed: the video widget reports the footage's native size as its size hint, the panel's scroll area grows to it, and every control below the preview leaves the screen, Stop included. Independently, the user finds the preview too small to judge footage and asks for a layout they can adjust: a collapsible left rail and user resizable centre and right columns.

## What Changes

- The preview stage SHALL keep a 16:9 aspect locked to its width, with the video widget unable to impose a size hint, so the panel's content height does not depend on the footage. A test adds a video widget with a large size hint and asserts the panel content's height stays bounded.
- The Review screen's centre column and right panel SHALL sit in a splitter the user drags, with the panel between a minimum and the window's width less the grid minimum, and the preview growing with the panel. The split SHALL be remembered per machine, outside the manifest.
- The left rail SHALL collapse to an icon only strip and expand again from a toggle at its foot, remembered per machine. Labels move to tooltips when collapsed.
- The Analysis, Soundtrack and Export screens SHALL keep their layouts; only the Review screen gains the splitter.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gui-shell`: collapsible rail and the per machine layout memory.
- `gui-review`: splitter between grid and panel, aspect locked preview, bounded panel height.

## Impact

`autocut/gui/widgets/{rail,preview}.py`, `autocut/gui/screens/review.py`, `autocut/gui/app.py`, a new `autocut/gui/layout.py` for the per machine layout file beside `recent.json` under the platformdirs config directory, `autocut/gui/theme/tokens.py` for the collapsed rail width and the panel minimum. No core, manifest or config change.

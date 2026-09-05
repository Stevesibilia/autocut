## Why

The GUI works but looks like a stock Qt form: the Fusion style with the desktop palette, a list widget for navigation, grey boxes for thumbnails and four ad hoc `setStyleSheet` colours. The user reviewed a design mockup of the Review screen (dark, slim icon rail, rounded cards with pill badges, one accent colour, a mono face for numbers, a unified timeline language) and approved it. This change applies that design system to the whole window so the application looks the same on Linux and macOS.

## What Changes

- A `gui/theme` package holding design tokens (colours, type scale, spacing, radii), a QSS generator, bundled fonts and a bundled stroke icon set. Painter widgets read their colours from the tokens instead of module constants.
- The application applies the Fusion style with a token palette and the generated stylesheet on every platform, defaulting to the dark theme, with `system` and `light` as user settings. **BREAKING** for the current behaviour on macOS, where the native style was left untouched.
- Space Grotesk (text) and IBM Plex Mono (numbers, timecodes, scores) ship inside the package and are registered at startup; Lucide icons ship as SVG and are recoloured from the tokens at render time.
- The window gets a slim left rail with icons and labels, a top bar with project name, counters and primary actions, and a status block for this machine's capabilities.
- The Review screen matches the approved mockup: filter chips, rounded cards with `IN n`, `KEPT n`, `OUT` and `REJECTED` badges, duration and beat count, tag chips, place and time, a highlighted current pick, the montage timeline strip with key hints at the bottom, and a right panel with preview, trim, the diversity slider first and the weights below it.
- Analysis, Soundtrack, Export and Project screens adopt the same tokens, controls and empty states without changing behaviour.

## Capabilities

### New Capabilities

- `gui-theme`: design tokens, generated stylesheet, bundled fonts and icons, theme setting, cross platform consistency.

### Modified Capabilities

- `gui-shell`: the theme requirement changes from "follow the OS" to "dark by default, system or light on request, same look on Linux and macOS"; the navigation becomes an icon rail plus a top bar.
- `gui-review`: card anatomy, badges, chips, the right panel order and the timeline strip are now specified.

## Impact

- `autocut/gui/app.py` (style, palette, rail, top bar), every screen under `autocut/gui/screens/`, and the painter widgets `thumb_grid.py`, `groups.py`, `waveform.py`, `montage.py`, `preview.py`, `sliders.py`.
- New package data under `autocut/gui/theme/assets/` (two font families, about twenty SVG icons) added to the wheel through `pyproject.toml` artifacts, plus a third party licence file. No new Python dependency: `QtSvg` is part of PySide6 Essentials.
- `autocut.toml` gains `gui.theme`; `SPEC.md` section on the GUI and a new ADR 10 record the decision to bundle a design system and to drop the native macOS style.
- The PyInstaller bundle (ADR 7, M6) must collect the asset directory.

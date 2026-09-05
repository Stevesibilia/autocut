## MODIFIED Requirements

### Requirement: Bundled icons

Navigation, actions and badges SHALL use a bundled set of stroke SVG icons recoloured from the active tokens at render time and rendered sharp at the widget's device pixel ratio, the whole glyph filling the requested logical size at every ratio. Icons SHALL be loaded through an icon registry keyed by name, never by path from screen code.

#### Scenario: Recoloured icon

- **WHEN** the Review rail item is active
- **THEN** its icon renders in the accent colour, and in the muted colour when inactive

#### Scenario: HiDPI

- **WHEN** an icon is rendered at 16 logical pixels for device pixel ratio 2
- **THEN** the pixmap is 32 pixels wide with ratio 2, and the glyph reaches its bottom right quadrant (painted pixels exist there), not only the top left one

### Requirement: Theme setting

A `gui.theme` setting SHALL accept `dark`, `light` and `system`, default `dark`, be editable in the settings dialog and apply on the next start. `system` SHALL pick dark or light from the OS palette at startup. `autocut gui --diagnose` SHALL print, without opening a window for interaction, every screen's geometry, available geometry and device pixel ratio, the font families registered and the ones in use, the theme resolved, the window's minimum size hint and its opening size, then exit zero.

#### Scenario: Default

- **WHEN** no `gui.theme` is set
- **THEN** the window opens dark on both platforms

#### Scenario: Follow the system

- **WHEN** `gui.theme` is `system` and the OS palette is light
- **THEN** the light token set is applied

#### Scenario: Diagnose

- **WHEN** `autocut gui --diagnose` runs on the offscreen platform
- **THEN** it prints one line per screen with geometry and ratio, the two font families, the theme, the minimum size hint and the opening size, and exits zero

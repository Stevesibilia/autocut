# gui-theme Specification

## Purpose

TBD - created by archiving change m5-visual-design. Update Purpose after archive.

## Requirements

### Requirement: Design tokens

The GUI SHALL define its colours, type scale, spacing and radii once, in a token module under `autocut/gui/theme`, with one dark and one light token set. Widgets and painters SHALL read colours from the active token set and SHALL NOT hardcode colour literals or pixel sizes outside that module. The type scale SHALL be 11 px (badges and uppercase eyebrow labels), 12 (body), 13 (card titles), 16 (headings), 18 (counters) and 20 (display), and every spacing, control height and panel width SHALL sit on an 8 px grid.

#### Scenario: One source of colour

- **WHEN** the repository is searched for colour literals under `autocut/gui/` outside `autocut/gui/theme/`
- **THEN** none is found

#### Scenario: Two complete sets

- **WHEN** the dark and light token sets are compared
- **THEN** they define the same field names and every field has a value in both

### Requirement: Generated stylesheet

The application SHALL apply the Fusion style, a palette built from the active tokens and a stylesheet generated from them on every platform. The generated stylesheet SHALL contain no unresolved placeholder and SHALL style buttons, inputs, sliders, combo boxes, scroll bars, list views, tool tips and the navigation rail.

#### Scenario: Same look on both platforms

- **WHEN** the window opens on Linux and on macOS with the same theme setting
- **THEN** both use the Fusion style with the same palette and stylesheet, and no native style is applied

#### Scenario: Stylesheet renders

- **WHEN** the stylesheet is generated from either token set
- **THEN** it parses without warnings from Qt and contains no `{` placeholder token

### Requirement: Bundled fonts

Space Grotesk (Regular, Medium, Bold; the family publishes no static SemiBold) and IBM Plex Mono (Regular, Medium) SHALL ship as package data and be registered with the font database at startup. Text SHALL use Space Grotesk; scores, durations, timecodes, BPM and counters SHALL use IBM Plex Mono. When a bundled font fails to register the application SHALL fall back to the platform sans and monospace fonts and log one warning, never fail.

#### Scenario: Fonts registered

- **WHEN** the application starts on a machine without either font installed
- **THEN** both families are available to Qt and the window uses them

#### Scenario: Registration fails

- **WHEN** the font files are missing from the installation
- **THEN** the window opens with the platform fonts and one warning is logged

### Requirement: Bundled icons

Navigation, actions and badges SHALL use a bundled set of stroke SVG icons recoloured from the active tokens at render time and rendered sharp at the widget's device pixel ratio. Icons SHALL be loaded through an icon registry keyed by name, never by path from screen code.

#### Scenario: Recoloured icon

- **WHEN** the Review rail item is active
- **THEN** its icon renders in the accent colour, and in the muted colour when inactive

#### Scenario: HiDPI

- **WHEN** the window runs at device pixel ratio 2
- **THEN** icons render at twice the pixel size without blur

### Requirement: Theme setting

A `gui.theme` setting SHALL accept `dark`, `light` and `system`, default `dark`, be editable in the settings dialog and apply on the next start. `system` SHALL pick dark or light from the OS palette at startup.

#### Scenario: Default

- **WHEN** no `gui.theme` is set
- **THEN** the window opens dark on both platforms

#### Scenario: Follow the system

- **WHEN** `gui.theme` is `system` and the OS palette is light
- **THEN** the light token set is applied

### Requirement: Third party licences

The bundled fonts and icons SHALL be redistributed under their licences (SIL Open Font License 1.1 for both font families, ISC for Lucide) with the licence texts shipped beside the assets and listed in the README.

#### Scenario: Licence present

- **WHEN** the wheel is built
- **THEN** it contains the asset directory with a licence file for each bundled family and for the icon set

## MODIFIED Requirements

### Requirement: Entry point and window

`autocut gui [project]` SHALL open a main window with a slim left rail over five screens: Project, Analysis, Review, Soundtrack, Export, each with an icon and a label, the active one marked in the accent colour. A top bar SHALL show the project name, the file and candidate counts, the selected clip count, the edit duration and the synced BPM when present, plus the primary actions of the current screen. The rail SHALL end with a block naming this machine's ffmpeg version, the embedding backend and whether cloud is on, and a toggle that collapses the rail to an icon only strip of `gui.rail_collapsed_width` (default 56 px) with the labels on tooltips, and expands it again. Screens later in the flow SHALL be disabled until their prerequisites exist in the manifest (analysis before review, selection before soundtrack and export). When the `gui` extra is not installed the command SHALL exit non-zero with a one line message naming the extra.

The window SHALL be resizable down to `gui.min_window` (default 1100x680) with any screen shown and a project loaded, and SHALL open no larger than the available screen. No row of controls SHALL impose a minimum width beyond that: rows that do not fit SHALL wrap or scroll, and panels taller than the window SHALL scroll. The first size on a screen SHALL be the smaller of the design size (1440x900) and the available screen geometry.

Layout choices the user makes (rail collapsed, Review split position, Review panel visible) SHALL be remembered per machine in a layout file in the application's configuration directory, never in the manifest, and restored at the next start.

#### Scenario: Fresh start

- **WHEN** `autocut gui` runs without a project
- **THEN** the Project screen is shown, the other four rail items are disabled, and the top bar shows no counters

#### Scenario: Missing extra

- **WHEN** PySide6 is not importable
- **THEN** the command prints that the `gui` extra is required and exits non-zero

#### Scenario: Laptop display

- **WHEN** the window opens on a 1440x900 display with the Review screen and a 60 candidate project
- **THEN** it fits the screen, and dragging its corner down to 1100x680 succeeds with every control still reachable

#### Scenario: Minimum size hint

- **WHEN** each screen is shown offscreen with the synthetic project loaded
- **THEN** the window's minimum size hint is at most 1100x680

#### Scenario: Collapsed rail

- **WHEN** the user presses the rail toggle
- **THEN** the rail is 56 px wide with icons only and tooltips, the grid gains the width, and the next start opens with the rail collapsed

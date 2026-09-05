## MODIFIED Requirements

### Requirement: Entry point and window

`autocut gui [project]` SHALL open a main window with a slim left rail over five screens: Project, Analysis, Review, Soundtrack, Export, each with an icon and a label, the active one marked in the accent colour. A top bar SHALL show the project name, the file and candidate counts, the selected clip count, the edit duration and the synced BPM when present, plus the primary actions of the current screen. The rail SHALL end with a block naming this machine's ffmpeg version, the embedding backend and whether cloud is on. Screens later in the flow SHALL be disabled until their prerequisites exist in the manifest (analysis before review, selection before soundtrack and export). When the `gui` extra is not installed the command SHALL exit non-zero with a one line message naming the extra.

#### Scenario: Fresh start

- **WHEN** `autocut gui` runs without a project
- **THEN** the Project screen is shown, the other four rail items are disabled, and the top bar shows no counters

#### Scenario: Missing extra

- **WHEN** PySide6 is not importable
- **THEN** the command prints that the `gui` extra is required and exits non-zero

### Requirement: Language and theme

Every visible string SHALL be English. The window SHALL render with the design tokens of the `gui-theme` capability, dark by default, light or following the OS when `gui.theme` says so, identically on Linux and macOS.

#### Scenario: Dark mode

- **WHEN** the application starts with the default settings on a light macOS desktop
- **THEN** the window renders with the dark token set and the Fusion style

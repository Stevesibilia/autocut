# gui-shell Specification

## Purpose

The GUI shell is the window, the navigation and the machinery under every screen: one state object over the manifest, worker threads for core stages, and autosave.
## Requirements
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

### Requirement: Single state object

All manifest and configuration changes SHALL go through a `ProjectState` that emits Qt signals for segment changes, selection changes, progress, stage completion and errors. Screens MUST NOT call core functions directly.

#### Scenario: Two screens, one change

- **WHEN** the state marks a segment as user-rejected
- **THEN** every bound view updates from the same signal without polling

### Requirement: Worker threads and cancellation

Core stages SHALL run in a worker thread, one at a time, with progress delivered as signals to the UI thread. Cancel SHALL stop the stage between units of work using the core's cancellation callback, leaving the manifest consistent, and MUST NOT kill the process. An exception in a stage SHALL surface as an error dialog, not a crash.

#### Scenario: UI stays responsive

- **WHEN** analysis of 72 files is running
- **THEN** the window repaints and reacts to clicks throughout, and the progress bar advances per file

#### Scenario: Cancel

- **WHEN** the user cancels after the third file
- **THEN** the run stops before the fourth, the manifest holds three analyzed files, and the Analysis screen offers to resume

#### Scenario: Stage error

- **WHEN** a stage raises
- **THEN** a dialog shows the message and the window remains usable

### Requirement: Autosave

The state SHALL write the manifest at most `gui.autosave_seconds` (default 5) after any mutation and on window close, using the atomic write the core already uses.

#### Scenario: Crash tolerance

- **WHEN** the process is killed 10 s after the last review action
- **THEN** reopening the project shows that action

### Requirement: Language and theme

Every visible string SHALL be English. The window SHALL render with the design tokens of the `gui-theme` capability, dark by default, light or following the OS when `gui.theme` says so, identically on Linux and macOS.

#### Scenario: Dark mode

- **WHEN** the application starts with the default settings on a light macOS desktop
- **THEN** the window renders with the dark token set and the Fusion style

### Requirement: Closing during a stage

Closing the window while a stage runs SHALL cancel the stage, keep the window open with a status message, and close the window once the stage has ended. The manifest SHALL be saved only after the worker has stopped writing it. Closing SHALL NOT block the UI thread while it waits. Closing a project SHALL report failure, and SHALL NOT save, when the stage does not stop within `gui.close_wait_ms`.

#### Scenario: Close during export

- **WHEN** the user closes the window while an export is encoding a clip
- **THEN** the window stays open with a message, the export stops after the current clip, the manifest is saved once, and the window closes

#### Scenario: Stage does not stop in time

- **WHEN** a project is closed and its stage does not stop within `gui.close_wait_ms`
- **THEN** closing reports failure, nothing is saved, and the project stays open

### Requirement: Worker lifetime

A worker thread SHALL be released once its stage has ended.

#### Scenario: Several stages

- **WHEN** the user runs three stages one after another
- **THEN** no finished worker thread remains alive


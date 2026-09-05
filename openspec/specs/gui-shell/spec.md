# gui-shell Specification

## Purpose

The GUI shell is the window, the navigation and the machinery under every screen: one state object over the manifest, worker threads for core stages, and autosave.

## Requirements

### Requirement: Entry point and window

`autocut gui [project]` SHALL open a main window with a slim left rail over five screens: Project, Analysis, Review, Soundtrack, Export, each with an icon and a label, the active one marked in the accent colour. A top bar SHALL show the project name, the file and candidate counts, the selected clip count, the edit duration and the synced BPM when present, plus the primary actions of the current screen. The rail SHALL end with a block naming this machine's ffmpeg version, the embedding backend and whether cloud is on. Screens later in the flow SHALL be disabled until their prerequisites exist in the manifest (analysis before review, selection before soundtrack and export). When the `gui` extra is not installed the command SHALL exit non-zero with a one line message naming the extra.

#### Scenario: Fresh start

- **WHEN** `autocut gui` runs without a project
- **THEN** the Project screen is shown, the other four rail items are disabled, and the top bar shows no counters

#### Scenario: Missing extra

- **WHEN** PySide6 is not importable
- **THEN** the command prints that the `gui` extra is required and exits non-zero

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

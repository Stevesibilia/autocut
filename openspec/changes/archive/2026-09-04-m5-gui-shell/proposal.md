## Why

Every stage of AutoCut works from the command line, and the user has said from the start that the final product is a desktop application. Milestone M5 builds it as a consumer of the existing core (SPEC.md sections 5 and 11). This first change lays the foundation every screen needs: the state object, worker threads, autosave, the window with its navigation, and the two screens that run before any review, project setup and analysis.

## What Changes

- `autocut gui` entry point and a PySide6 main window with a left navigation over five screens (Project, Analysis, Review, Soundtrack, Export), the last three placeholders until their changes land.
- `ProjectState`: owns manifest and config, Qt signals for changes, debounced autosave, open and create project (ADR 9).
- `CoreWorker`: runs any core stage on a `QThread` with the progress callback bound to signals and cooperative cancellation, one at a time, with an error signal that never crashes the window.
- Project screen: drag and drop or browse source folders, output folder, profile picker (drone, family, mixed) that presets config, open an existing manifest, recent projects.
- Analysis screen: runs analyze, embed, tag and describe through the worker with a progress bar, current file, estimated time left, cancel, and resume of an interrupted run from the manifest; shows the doctor report before the first run.
- Settings dialog: cloud toggle, API key entry through the keychain (`autocut key set` logic), hardware decoder, cache location and size, theme following the OS.
- Test infrastructure: `pytest-qt` in the `dev` extra, offscreen Qt platform in a `dev-gui` Docker target, screenshot capture of every screen on the synthetic project into a scratch directory for review, never committed.

## Capabilities

### New Capabilities

- `gui-shell`: window, navigation, state object, worker threads, autosave.
- `gui-project`: project creation, opening and source configuration.
- `gui-analysis`: running and cancelling the analysis pipeline with progress.

### Modified Capabilities

None in the core. The GUI consumes existing capabilities.

## Impact

- New package layout under `autocut/gui/`: `app.py`, `state.py`, `workers.py`, `models.py`, `screens/`, `widgets/`, `settings.py`, `resources/`.
- `autocut/cli/main.py`: `gui` command that imports the package lazily and fails with a clear message when the `gui` extra is missing.
- `pyproject.toml`: `pytest-qt` in `dev`, `gui` extra pinned; `Dockerfile.dev` gains a `gui` target with the Qt offscreen runtime libraries; CI gains a `gui` job.
- No core changes; the analysis stages already emit the progress events and honor cancellation.

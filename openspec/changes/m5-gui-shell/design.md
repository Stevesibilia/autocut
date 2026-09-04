## Context

The core is complete for the command line and follows one contract: stages take a manifest and config, report through `ProgressCallback`, cancel through an exception raised by that callback, and never print. ADR 9 decides the GUI shape: one state object, worker threads, thin screens. SPEC.md section 11 lists the five screens and the cross-cutting requirements. The `gui` extra exists in `pyproject.toml` but nothing uses it.

## Goals / Non-Goals

**Goals:**

- A window that never blocks and never loses work.
- Every core stage runnable from the GUI with the same results as the CLI.
- Testable offscreen in Docker and CI.

**Non-Goals:**

- The Review, Soundtrack and Export screens (next two changes).
- Packaging (M6).
- Any new core behavior.

## Decisions

**Package layout.** `autocut/gui/app.py` (QApplication, main window, navigation), `state.py` (ProjectState), `workers.py` (CoreWorker, CancelFlag), `models.py` (SegmentListModel, proxies), `screens/project.py`, `screens/analysis.py`, `screens/placeholder.py`, `settings.py`, `widgets/` for reusable pieces. Screens receive the state in their constructor.

**ProjectState.** Holds `Manifest`, `AutocutConfig`, output path. Methods mirror CLI commands (`run_analyze`, `run_select`, later `run_soundtrack`, `run_sync`, `run_export`) and hand a callable to the worker. Signals: `segments_changed(list[str])`, `selection_changed()`, `progress(ProgressEvent)`, `stage_started(str)`, `stage_finished(str)`, `error(str)`, `saved()`. A `QTimer` debounces saves; `save_now()` on close.

**CoreWorker.** One `QThread` subclass holding a callable and a `CancelFlag`. The progress callback given to the core emits `progress` and raises `AnalysisCancelled` when the flag is set. The core already catches that between files, so cancellation needs no new core code. Only one worker at a time; the state refuses a second run and the UI disables buttons while one runs.

**Resume.** `analyze_files` already skips files with a cache entry; resume is a normal run over the same sources, which the cache makes cheap. The screen labels it Resume when the manifest shows an incomplete run.

**Profiles.** Three dictionaries of config overrides in `autocut/gui/profiles.py`, applied onto the loaded config with a diff shown to the user. Kept in the GUI package because they are presentation of config, not core behavior.

**Settings.** A dialog bound to `AutocutConfig` fields that matter to a non-CLI user: cloud toggle, key (through `providers.set_key`), decoder, cache dir, weights and diversity (also exposed on the Review screen later). Writes `autocut.toml` next to the manifest so the CLI sees the same values.

**Theme.** Qt's platform theme follows the OS on macOS; on Linux the Fusion style with a palette derived from the OS hint. No custom styling beyond a small stylesheet for the navigation.

**Testing.** `pytest-qt` with `QT_QPA_PLATFORM=offscreen`. A `dev-gui` Docker target installs the Qt runtime libraries (libegl1, libxkbcommon0, libgl1, libfontconfig1, libdbus-1-3, libxcb-* set) and the `gui` extra. Tests build a state over the synthetic project, drive screens through `qtbot`, and grab each screen to PNG under a scratch directory for the reviewer; PNGs are never committed and only synthetic fixtures are shown. A `gui` marker keeps these tests out of the default matrix job; a `gui` CI job runs them.

**CLI.** `autocut gui` imports `autocut.gui.app` inside the function and catches `ImportError` to print the one line about the extra.

## Risks / Trade-offs

- [PySide6 wheel and Python 3.14 on macOS arm64] → the extra is pinned to a version with wheels; verified by tag audit like the `ai` extra; confirmed on the Mac at first install.
- [Offscreen tests do not catch layout ugliness] → screenshot capture for the reviewer on every PR; the user judges on the Mac.
- [Worker exceptions crossing threads] → caught in the worker, emitted as `error(str)` with the traceback logged to the project folder.
- [Autosave races with a running worker writing the manifest] → the worker never writes; it returns results and the state applies them on the UI thread, then saves.

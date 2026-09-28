## Why

Issue #80, from the 2026-09-28 project review. The window freezes during work that ADR 9 says belongs on the worker thread. Generating a soundtrack prompt with cloud refinement makes an HTTP request on the UI thread. Loading a track runs librosa beat tracking there, and the export summary walks the selects folder there. Closing the window during a stage can block for up to 70 seconds. If the wait runs out, the manifest is saved while the worker is still writing it.

## What Changes

- Prompt generation that calls a hosted provider SHALL run on the worker thread. Local generation stays immediate.
- Loading a track SHALL decode and measure it on the worker thread. The screen updates when the measurement is done.
- The export summary SHALL use a folder size measured by the export worker.
- Closing the window during a stage SHALL cancel the stage and close the window once the stage ends, without blocking the UI and without saving while the worker runs.
- Finished worker threads SHALL be released.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gui-shell`: closing during a stage; worker lifetime.
- `gui-soundtrack`: generation and track loading off the UI thread.
- `gui-export`: summary size measured off the UI thread.

## Impact

`autocut/gui/screens/soundtrack.py`, `autocut/gui/screens/export.py`, `autocut/gui/state.py`, `autocut/gui/app.py`, one field in `autocut/core/config.py` (`GuiConfig.close_wait_ms`), `tests/unit/test_gui_soundtrack.py`, `tests/unit/test_gui_export.py`, the GUI shell tests, `SPEC.md` §11, `CHANGELOG.md`.

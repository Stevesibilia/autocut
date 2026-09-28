## Context

Read on `main` at `5f7aeec`:

- `SoundtrackScreen.generate` (`autocut/gui/screens/soundtrack.py:316`) calls `build_soundtrack(..., provider=self._provider())` on the UI thread. With the cloud on and a key stored, `_provider()` (`:344`) returns an OpenRouter text provider, and the prompt refinement is an HTTP request made while the window is frozen. With no provider, `build_soundtrack` is local computation over the manifest. `generate` is also called on every genre change and BPM edit through `_regenerate_from_controls` (`:424`, wired at `:96` and `:100`).
- `SoundtrackScreen.load_track` (`:486`) calls `decode_audio`, `measure_track` (librosa beat tracking, seconds for a full song) and `load_or_build_envelope` on the UI thread.
- `ExportScreen.describe` (`autocut/gui/screens/export.py:595`) calls `folder_size` (`:86`), an `rglob` over the selects folder, on the UI thread from `_stage_finished` (`:582`).
- `ProjectState.close_project` (`autocut/gui/state.py:248`) calls `wait_for_stage()` (60 s default), ignores its result, and then calls `save_now(force=True)`. If the wait timed out, the save serialises the manifest while the worker is still writing it. `MainWindow.closeEvent` (`autocut/gui/app.py:330`) already waits 10 s before calling `close_project`, so the window can hang for 70 s. `close_project` has no other caller.
- `ProjectState._clear_worker` (`state.py:~365`) drops the reference to a finished `CoreWorker` but never calls `deleteLater`, so each stage leaves a QThread object parented to the state.
- `run_stage` (`state.py:~300`) is the one way to run work on the worker thread. It refuses a second stage while one runs, emits `stage_started` before starting, and stores the callable's return value in `last_result` before `stage_finished`.
- Tests call `screen.generate()` and `screen.load_track(...)` synchronously and assert right after: `tests/unit/test_gui_soundtrack.py`, 24 call sites.

## Decisions

**1. `generate` goes to the worker only when it will make a network call.** When `_provider()` returns `None`, `generate` stays synchronous, as today. When it returns a provider, `generate` runs `build_soundtrack` through `state.run_stage("soundtrack", work)` and returns the result of `run_stage`. The UI updates that follow `build_soundtrack` today move into a private `_after_generate(result)`, called directly on the synchronous path and from `_stage_finished` when `name == "soundtrack"` and `last_result` is a `SoundtrackResult` (`autocut/core/soundtrack/build.py:70`). Reason: the local path takes milliseconds, and keeping it synchronous keeps the 24 synchronous test call sites and the instant feedback of the genre box. Only the network call can freeze the window.
While a stage runs, `_regenerate_from_controls` sets `self._regenerate_pending = True` instead of calling `generate`. `_stage_finished` calls `generate()` once when the flag is set and clears it. This avoids the "still running" error for a user who changes the genre twice quickly.

**2. `load_track` always goes to the worker.** `load_track(path)` starts `state.run_stage("track", work)` and returns its result. `work` does `decode_audio`, `measure_track` and `load_or_build_envelope` and returns a new frozen dataclass `TrackLoad(path, track, pairs, error)`. `AudioUnavailableError` is caught inside `work` and returned as `TrackLoad(path=path, error=str(error))`, so it is not reported as a stage failure. Everything after the measurement in today's `load_track` (widgets, `manifest.soundtrack.*`, `_describe_comparison`, button states, `schedule_save`, `refresh_preview`) moves to `_after_track(load)`, called from `_stage_finished` when `name == "track"`. The manifest is written only there, on the UI thread. Add a signal `track_loaded = Signal(bool)` on the screen, emitted at the end of `_after_track` with success or failure, so tests and callers can wait on it.
Tests: add a helper in `tests/unit/test_gui_soundtrack.py`, `def load(screen, qtbot, path) -> bool`, that wraps `qtbot.waitSignal(screen.track_loaded, timeout=30_000)` around `screen.load_track(path)` and returns the signal's argument. Replace the synchronous calls with it. `assert screen.load_track(broken) is False` becomes `assert load(screen, qtbot, broken) is False`.

**3. The export size is measured by the worker.** Add `selects_bytes: int = 0` to `ExportOutcome` (`export.py:75`). At the end of `work` in `start` (`export.py:~550`), set `outcome.selects_bytes = folder_size(outcome.export.selects_dir or Path(manifest.output_dir) / SELECTS_DIR)`. `describe` gains a keyword `selects_bytes: int | None = None`. When it is `None`, `describe` calls `folder_size` as today, so the direct test at `tests/unit/test_gui_export.py:480` keeps working. `_stage_finished` passes `outcome.selects_bytes`.

**4. Closing never saves under a running worker and never blocks.**

- `close_project` returns `bool`. When a stage is running, it cancels and waits up to `config.gui.close_wait_ms`. If the wait fails, it returns `False` without saving and without clearing `manifest` or `output_dir`. Otherwise it saves, clears and returns `True`. Add `close_wait_ms: int = Field(default=5000, ge=0, le=120_000, description=...)` to `GuiConfig`, per AGENTS.md "tunables live in config".
- `MainWindow.closeEvent`: save the layout. If no stage is running, call `close_project()` and accept, as today. If a stage is running, call `state.cancel()`, connect the running worker's end to closing the window again (`state.stage_finished`, `state.stage_cancelled` and the failure path, whichever fires; a single-shot connection to the worker's `finished` signal through a new `ProjectState.stage_ended` signal is the cleanest, emitted from `_clear_worker`), show the status message `Stopping <stage name>; the window closes when the current file is done.`, and `event.ignore()`. When the worker ends, `closeEvent` runs again, finds nothing running, saves and accepts.
- Remove the fixed 10-second wait in `closeEvent`.

Reason: the cancel flag is only checked between files, so a long encode can run for minutes. Waiting on the UI thread freezes the window. Saving while the worker writes corrupts the manifest. Letting Python exit with a running QThread aborts the process. Deferring the close avoids all three. Rejected: `QThread.terminate()`, which can kill the thread while it holds a lock or has written half a file.

**5. Finished workers are deleted.** `_clear_worker` keeps a local reference, sets `self._worker = None`, emits `stage_ended` (decision 4), then calls `worker.deleteLater()`.

**6. Docs.** `SPEC.md` §11 GUI: one sentence that network calls, audio analysis and folder walks never run on the UI thread, and that closing during a stage waits for the current file without freezing the window. `CHANGELOG.md` `### Fixed` lines.

**7. Media players stop from the event loop.** Found in review under Docker: `QMediaPlayer.stop()` called from Python holds the GIL while the FFmpeg backend tears down its audio renderer. That renderer's `~QObject` holds Qt's signal-slot mutex and asks Shiboken for the GIL (`disconnectNotify` override lookup), while the UI thread in `stop()` waits for the same mutex, and the window freezes. `MontagePlayer` and `PreviewPanel` therefore queue their native teardown calls (`QMetaObject.invokeMethod(..., QueuedConnection)`), so they run from the event loop with the GIL released, and the test teardown spins one event-loop turn after queuing. Rejected: a tests-only queued stop (it hides a product freeze) and leaving it upstream (a flaky gui job).

## Not touched

- Core modules other than the one `GuiConfig` field in `autocut/core/config.py`. The #78 branch changes the core, and this change must merge independently of it. `config.py` will conflict trivially with #78's base-class change; whichever merges second takes both.
- Cancelling a running subprocess mid-file.
- `run_analysis`, `run_select` and the other stages, which already use `run_stage`.

## Risks / Trade-offs

- **`build_soundtrack` writes the manifest.** On the worker path, the worker mutates the manifest. That is the same contract as every other stage, which is why `run_stage` stops the save timer. If `build_soundtrack` also touches Qt objects, report it: the worker must not.
- **A test relies on `generate()` returning after the network call** with a fake provider. Such a test now needs to wait for `stage_finished`. Add the wait, and list those tests in the hand-back.
- **`closeEvent` re-entrancy.** `QWidget.close()` from a slot runs `closeEvent` again. If the second pass finds the stage still running (because `stage_ended` fired before `is_running` turned false), you have an ordering bug. Assert the order in a test. Do not add a timer.
- **The window is closed while a track loads.** Covered by decision 4. `_after_track` must not run after `close_project` has cleared the manifest: guard it with `if self._state.manifest is None: return`.

## Migration Plan

None.

## Open Questions

None.

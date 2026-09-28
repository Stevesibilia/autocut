## 1. Close and worker lifetime (design decisions 4 and 5), one commit

- [ ] 1.1 `GuiConfig.close_wait_ms`, `ProjectState.stage_ended`, `close_project -> bool`, `_clear_worker` with `deleteLater`, and the deferred `closeEvent`.
- [ ] 1.2 Tests (GUI shell and state test files):
  - closing during a stage whose work blocks on a `threading.Event` leaves the window open with the status message; setting the event lets the stage end, and the window then closes and the manifest is saved once (count calls to `Manifest.save` with a monkeypatch);
  - `close_project` with a stage that ignores cancel and `close_wait_ms=50` returns `False`, and `Manifest.save` is not called;
  - after three stages, `state._worker is None`, and the previous workers' `destroyed` signal fired (`qtbot.waitSignal(worker.destroyed)`).
- [ ] 1.3 Commit: `fix(gui): close after the running stage ends instead of saving under it`.

## 2. Soundtrack off the UI thread (decisions 1 and 2), one commit

- [ ] 2.1 `generate` with the provider path on `run_stage`, `_after_generate`, `_regenerate_pending`; `load_track` on `run_stage`, `TrackLoad`, `_after_track`, `track_loaded`.
- [ ] 2.2 Tests in `tests/unit/test_gui_soundtrack.py`:
  - the `load` helper, with every synchronous `load_track` call site converted;
  - a fake provider whose `complete` blocks on an event: `generate()` returns `True`, `state.is_running` is `True`, and the variants appear after the event is set and `stage_finished` fires;
  - two genre changes during a running generation lead to exactly one extra `generate` after it finishes;
  - the broken-file case shows the reason in the track label and emits `track_loaded(False)`, with no `state.error` emission.
- [ ] 2.3 Commit: `fix(gui): generate with a hosted model and measure tracks off the ui thread`.

## 3. Export size (decision 3) and docs (decision 6), one commit

- [ ] 3.1 `ExportOutcome.selects_bytes`, the worker measurement, and `describe(..., selects_bytes=...)`.
- [ ] 3.2 Test in `tests/unit/test_gui_export.py`: after an export stage, `folder_size` is not called on the UI thread. Monkeypatch it to record `threading.current_thread()` and assert it is not the main thread.
- [ ] 3.3 `SPEC.md` §11 and `CHANGELOG.md`, each formatted with `sjust format-md <path>`.
- [ ] 3.4 Commit: `fix(gui): measure the export folder on the worker thread`.

## 4. Gates and hand-back

- [ ] 4.1 `make lint` in this worktree's venv (`make venv` first; it has the gui extra, so mypy covers `autocut/gui`).
- [ ] 4.2 `openspec validate gui-worker-offload --strict`.
- [ ] 4.3 Through the test runner: `make test`, and `make docker-test-gui`. Quote the counts.
- [ ] 4.4 Real run on the host (macOS, the target platform): `autocut gui` on a project built from `tests/fixtures/synthetic`. Load `click` from the fixtures as a track, and check that the window stays movable while it loads. Start an export and close the window mid-export: the window closes by itself after the clip. Describe what you saw in the hand-back. You cannot screenshot a claim, so say plainly what you could not observe.
- [ ] 4.5 Tick these boxes, push the branch and hand back.

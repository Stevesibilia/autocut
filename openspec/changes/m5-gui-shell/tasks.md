## 1. Infrastructure

- [ ] 1.1 Pin the `gui` extra to a PySide6 version with wheels for Linux x86_64 and macOS arm64 on Python 3.11 to 3.14 (verify on PyPI per AGENTS.md), add `pytest-qt` to `dev`, add a `gui` pytest marker skipped when PySide6 does not import. Verify `pip install -e ".[dev,gui]"` in the venv and the marker skip in the default suite.
- [ ] 1.2 Add a `gui` target to `Dockerfile.dev` with the Qt offscreen runtime libraries, a `dev-gui` compose service with `QT_QPA_PLATFORM=offscreen`, `make docker-test-gui`, and a `gui` CI job. Verify `docker compose run --rm dev-gui pytest -q -m gui` runs.
- [ ] 1.3 Add `autocut gui [project]` to the CLI with the lazy import and the missing-extra message. Verify with a `CliRunner` test that mocks the import failure.

## 2. State and workers

- [ ] 2.1 Add `autocut/gui/state.py` with `ProjectState` (manifest, config, signals, debounced autosave, `open_project`, `new_project`, `save_now`). Verify with `qtbot` tests: a mutation emits the signal, the manifest is written within the debounce, `save_now` on close writes immediately.
- [ ] 2.2 Add `autocut/gui/workers.py` with `CoreWorker` and `CancelFlag`, and `ProjectState.run_stage(name, callable)`. Verify with tests: progress events arrive on the UI thread, cancel stops between units, an exception becomes an `error` signal, a second run while one is active is refused.
- [ ] 2.3 Add `autocut/gui/models.py` with `SegmentListModel` over the manifest and a sort and filter proxy. Verify with model tests for row count, roles and re-sort on `segments_changed`.

## 3. Window and screens

- [ ] 3.1 Add `autocut/gui/app.py` with the main window, navigation, screen enabling rules, theme following the OS, and placeholder screens for Review, Soundtrack and Export. Verify with `qtbot` tests for the enabling rules on empty, analyzed and selected manifests.
- [ ] 3.2 Add `screens/project.py`: drag and drop and browse for sources, counts, output folder, existing manifest detection, profiles with diff, open project, recent list stored in the platform config dir, inline doctor report. Verify with `qtbot` tests for the drop, existing manifest, family profile and reopen scenarios.
- [ ] 3.3 Add `screens/analysis.py`: stage steps, progress bar, current file, elapsed and estimate, cancel, resume, warnings and summary, re-run and clear cache. Verify with `qtbot` tests driving `analyze` on the synthetic project including a cancel after the third file and a resume.
- [ ] 3.4 Add `settings.py` with the dialog and `autocut.toml` writing. Verify with a test that a changed weight lands in the file and in the state config.

## 4. Screenshots and validation

- [ ] 4.1 Add a `gui` marked test that opens each screen on the synthetic project and saves a PNG per screen to `$AUTOCUT_GUI_SHOTS` when set (scratch directory, never committed). Verify the files exist and put their paths in the PR body for the reviewer.
- [ ] 4.2 Run the GUI on the Linux host against the real Sardinia folder end to end: new project, analyze with cancel and resume, reopen. Record in this task: whether the UI stayed responsive, the analysis time, and any warning shown. Take no screenshots of real footage.
- [ ] 4.3 Update `SPEC.md` section 11 (screens 1 and 2) and `README.md` (gui command). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-gui-shell` following `sf-commit-convention`, open a pull request.

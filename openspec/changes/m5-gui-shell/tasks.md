## 1. Infrastructure

- [x] 1.1 Pin the `gui` extra to a PySide6 version with wheels for Linux x86_64 and macOS arm64 on Python 3.11 to 3.14 (verify on PyPI per AGENTS.md), add `pytest-qt` to `dev`, add a `gui` pytest marker skipped when PySide6 does not import. Verify `pip install -e ".[dev,gui]"` in the venv and the marker skip in the default suite.

  Pinned to `PySide6>=6.11.2,<6.12`. Checked on PyPI: 6.11.2 was published 2026-08-18, is a meta package pinning `shiboken6`, `PySide6-Essentials` and `PySide6-Addons` to the same version, and all four publish `cp310-abi3` wheels for `manylinux_2_34_x86_64` and `macosx_13_0_universal2` and declare `>=3.10,<3.15`. One abi3 wheel therefore serves 3.11 through 3.14 on both platforms this project targets, which is why the bound is on the Qt version and not on the interpreter. Installed into the venv on Python 3.14.7, nothing on the host.

  **Departure from the task, worth a review comment:** `pytest-qt` is not in `dev`. It refuses to load without a Qt binding and fails the whole collection, not just the tests that need it, so `make docker-test` in the Qt free `dev` container could not run a single test with it there. It sits in its own `dev-gui` extra, installed alongside `gui` in `make venv` and in the Docker `gui` target. The `dev` extra and the CI matrix job stay Qt free. Verified both ways: the default Docker suite passes with no Qt at all, and the `gui` tests skip by marker in it.

- [x] 1.2 Add a `gui` target to `Dockerfile.dev` with the Qt offscreen runtime libraries, a `dev-gui` compose service with `QT_QPA_PLATFORM=offscreen`, `make docker-test-gui`, and a `gui` CI job. Verify `docker compose run --rm dev-gui pytest -q -m gui` runs.

  The target installs `libegl1`, `libxkbcommon0`, `libfontconfig1`, `libdbus-1-3` and `libglib2.0-0`: the wheel carries Qt itself but not the system libraries Qt links against. No X server and no `/dev/dri`, because the offscreen platform renders into memory. `make docker-test-gui` runs **92 passed, 1039 deselected in 24.2 s**.

- [x] 1.3 Add `autocut gui [project]` to the CLI with the lazy import and the missing-extra message. Verify with a `CliRunner` test that mocks the import failure.

  Four tests in `tests/unit/test_cli_gui.py`, none of which import Qt: the point of the command is that it can be typed on a machine without PySide6 and get a sentence. `None` in `sys.modules` is how the import machinery reports a blocked module, which is what the missing-extra test uses. The install line is escaped, because `[gui]` is Rich markup and Rich was eating the one part of the message the user has to type verbatim.

## 2. State and workers

- [x] 2.1 Add `autocut/gui/state.py` with `ProjectState` (manifest, config, signals, debounced autosave, `open_project`, `new_project`, `save_now`). Verify with `qtbot` tests: a mutation emits the signal, the manifest is written within the debounce, `save_now` on close writes immediately.

  16 tests. The debounce is 1500 ms; a burst of twenty mutations collapses into one save, which is what makes the live slider of section 11 affordable. `new_project` over a folder that already holds a manifest keeps the analysis in it. `open_project` reads `autocut.toml` beside the manifest, so the window and the CLI share one project. A `project_changed` signal was added beyond the task: a project can be opened from the command line or the recent list, and the Project screen has to show the project the rest of the window is working on.

- [x] 2.2 Add `autocut/gui/workers.py` with `CoreWorker` and `CancelFlag`, and `ProjectState.run_stage(name, callable)`. Verify with tests: progress events arrive on the UI thread, cancel stops between units, an exception becomes an `error` signal, a second run while one is active is refused.

  7 worker tests plus the state's. Progress delivery is asserted by thread identity, not trusted: the work runs on a thread that is not the main one and every slot call lands on the main one. Cancellation finishes the unit in flight and stops at the next report, which is what the core does too, and the test uses a gate rather than racing the event loop because the real cancel comes from a button press. A failing stage emits `error` and appends the traceback to `gui-errors.log` in the project folder. A stale cancel does not kill the next run.

- [x] 2.3 Add `autocut/gui/models.py` with `SegmentListModel` over the manifest and a sort and filter proxy. Verify with model tests for row count, roles and re-sort on `segments_changed`.

  13 tests. Ten roles, the order the report uses (selected clips first in edit order), and a proxy filtering by outcome, source class and dominant tag. A change is a full reset rather than a per row edit, because one clip winning can change the order of every other clip: there is no smaller honest signal. `invalidate` rather than `invalidateRowsFilter`, which PySide6 6.11 marks deprecated.

## 3. Window and screens

- [x] 3.1 Add `autocut/gui/app.py` with the main window, navigation, screen enabling rules, theme following the OS, and placeholder screens for Review, Soundtrack and Export. Verify with `qtbot` tests for the enabling rules on empty, analyzed and selected manifests.

  13 tests. `screen_available(spec, manifest)` is a function of the manifest alone, so the rules are tested without building widgets, and the same tests cover the window built around them. All five entries are listed from the first change: hiding two and adding them later would change the shape of the window under the user, and a placeholder that names the change that fills it is more use than a blank panel. Closing cancels a running stage and waits for it, so no thread outlives the window.

- [x] 3.2 Add `screens/project.py`: drag and drop and browse for sources, counts, output folder, existing manifest detection, profiles with diff, open project, recent list stored in the platform config dir, inline doctor report. Verify with `qtbot` tests for the drop, existing manifest, family profile and reopen scenarios.

  14 screen tests plus 8 for the recent list and 11 for the profiles, the last two groups needing no Qt and running in the default suite. Counts come from the extension rule alone rather than from `ingest`, which probes every file with ffprobe: the number shown before a run is the number the run will consider, without paying seconds for it. A dropped file counts as the folder holding it, because dragging a clip out of a card is how people show you where the footage is. `weights.faces` was dropped from the family profile and a test now forbids it: the field exists in the config but no face metric is computed, so a profile setting it would promise what the scoring cannot deliver.

- [x] 3.3 Add `screens/analysis.py`: stage steps, progress bar, current file, elapsed and estimate, cancel, resume, warnings and summary, re-run and clear cache. Verify with `qtbot` tests driving `analyze` on the synthetic project including a cancel after the third file and a resume.

  14 tests, two of them driving the real pipeline on the synthetic fixtures under the `ffmpeg` marker, including the cancel after the third file and the resume that finishes the job. The estimate stays blank until a second file has finished, because the first pays for every warm up there is and "42 minutes left" that becomes four is worse than nothing. Resume is offered when a probed file has neither a segment nor an error, which is what a cancel leaves behind; an unreadable file is not a reason to resume, since it will never produce a segment however often it runs.

- [x] 3.4 Add `settings.py` with the dialog and `autocut.toml` writing. Verify with a test that a changed weight lands in the file and in the state config.

  13 tests. The file is merged rather than replaced, so keys the dialog never saw survive a write and hand editing stays compatible; comments do not survive, which is the price of not taking a round tripping TOML editor as a dependency. A `None` value is removed rather than written, since the config's default for those fields means "work it out" and TOML has no null. A typed key goes to the keychain and a test asserts it is not in the file. `write_path` validates against the field's own type, because the config models do not validate on assignment.

## 4. Screenshots and validation

- [x] 4.1 Add a `gui` marked test that opens each screen on the synthetic project and saves a PNG per screen to `$AUTOCUT_GUI_SHOTS` when set (scratch directory, never committed). Verify the files exist and put their paths in the PR body for the reviewer.

  `tests/integration/test_gui_screenshots.py` analyses the synthetic fixtures, selects, then walks the five screens and grabs each. The grab runs whether or not a directory was given, because a screen that cannot be rendered is a bug worth failing on in CI where nobody collects images. Six files written (the five screens plus the empty window), 18 to 92 KB each, paths in the PR body. Nothing is committed and only synthetic fixtures are shown.

- [x] 4.2 Run the GUI on the Linux host against the real Sardinia folder end to end: new project, analyze with cancel and resume, reopen. Record in this task: whether the UI stayed responsive, the analysis time, and any warning shown. Take no screenshots of real footage.

  Driven offscreen through the real widgets, with a fresh cache directory so the timing is a cold run, against `~/Documents/autocut/test sardegna`, output in `~/Documents/autocut/edit-sardegna-m5-gui`. No screenshots taken.

  | Step                 | Result                                                                       |
  | -------------------- | ---------------------------------------------------------------------------- |
  | Project screen count | 72 clips across 1 folder, before any probing                                 |
  | Cancel               | Requested at the fifth analysed file, stopped 13.1 s in                      |
  | Saved on cancel      | 72 files probed, 6 segments from 6 files, button changed to Resume           |
  | Resume, cold cache   | Finished in 128.6 s, 77 segments from 72 files                               |
  | Selection            | 29 clips, which unlocked Review, Soundtrack and Export                       |
  | Reopen               | 72 files, 77 segments, 29 selected, source folder back on the Project screen |
  | Warnings             | None. No errors during the whole run                                         |

  **Responsiveness:** measured as the longest gap between two consecutive returns of the event loop on the main thread, which is what a user feels as a freeze. Worst gap 29 ms through the cancel run and 274 ms through the full run, the latter during the embedding pass. Nothing approaching the half second at which a window reads as stuck, and the analysis loop itself stayed under 30 ms.

- [x] 4.3 Update `SPEC.md` section 11 (screens 1 and 2) and `README.md` (gui command). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-gui-shell` following `sf-commit-convention`, open a pull request.

  Section 11 now records the state and worker shape, the navigation rule, what screens 1 and 2 actually do, the settings file contract and how the GUI is tested. The README's status line was stale at M0 and now says where the project is, and gained the `gui` extra, the `autocut gui` command and the two new Docker targets.

  Gates: `make lint` clean (ruff, `ruff format --check`, mypy strict on 58 source files). `make docker-test` **991 passed, 56 skipped**. `make docker-test-gui` **92 passed**. `make docker-test-ai` **8 passed, 8 skipped** (the skips are the GUI modules, which that image has no Qt for). In the venv, where both extras are installed, the whole suite is **1091 passed, 40 skipped**.

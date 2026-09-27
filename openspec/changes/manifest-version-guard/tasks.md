## 1. Deterministic back-to-grid test (#69), one commit

- [ ] 1.1 Before changing it, confirm the diagnosed mechanism: temporarily add `screen.montage._position_changed(0)` right after `screen.montage._announce(last)` and check that the test fails with `'f0:0' == 'f2:...'`, or with the equivalent ids of your run. Remove the line again and do not commit it. Record the output for the hand-back.
- [ ] 1.2 In `tests/unit/test_gui_review.py::test_coming_back_selects_the_clip_that_was_playing`, remove `qtbot.wait(50)` and extend the comment as in design decision 6.
- [ ] 1.3 Run that test 20 times in a row in the host venv (`.venv`, which has PySide6 and ffmpeg), then `tests/unit/test_gui_review.py` once in full. Record the pass counts.
- [ ] 1.4 Commit: `test(gui): stop the back-to-grid test racing the player`.

## 2. Version guard and migration step in the core (#70), one commit

- [ ] 2.1 `ManifestVersionError`, `_MIGRATIONS` and `_migrate` in `autocut/core/manifest.py`, and `Manifest.load` rewritten as in design decision 2.
- [ ] 2.2 Tests in `tests/unit/test_manifest.py`:
  - a newer version is refused: the message names both versions and the path, and the file's bytes are unchanged;
  - a missing `schema_version` loads as the current version;
  - a string `schema_version` is refused;
  - a top level that is not an object is refused;
  - a one-step migration runs: monkeypatch `MANIFEST_SCHEMA_VERSION` to 2 and `_MIGRATIONS` to `{1: step}`, then assert the step ran once and the result has version 2;
  - a missing step raises `RuntimeError`;
  - a current manifest round-trips through save and load unchanged.
- [ ] 2.3 `SPEC.md` §9 sentence and the `CHANGELOG.md` line from design decision 7.
- [ ] 2.4 Commit: `fix(core): refuse manifests from a newer schema`.

## 3. Front ends report the refusal (#70), one commit

- [ ] 3.1 `_load_manifest` in `autocut/cli/main.py` and its three call sites, as in design decision 4.
- [ ] 3.2 `except (OSError, ValueError)` in `autocut/gui/screens/project.py`, as in design decision 5.
- [ ] 3.3 Tests:
  - CLI: `autocut report` on a project with a version 2 manifest exits 1, the output names both versions and holds no `Traceback`, and the file is unchanged. Put it in the CLI test file closest to `report`, or in a new `tests/unit/test_cli_report.py` if none fits.
  - GUI: in `tests/unit/test_gui_project_screen.py`, the new-project path on a folder with a version 2 manifest shows the warning (monkeypatch `QMessageBox.warning`), leaves `state.manifest` as it was, and leaves the file unchanged after the autosave debounce has had time to fire.
- [ ] 3.4 Commit: `fix(cli,gui): report a manifest from a newer schema instead of crashing`.

## 4. Gates and hand-back

- [ ] 4.1 `make lint` in the venv. It covers `autocut/gui` because the venv has the `gui` extra.
- [ ] 4.2 Validate the change: `openspec validate manifest-version-guard --strict`.
- [ ] 4.3 Hand the suites to a test runner: `make test`, and the gui suite in `dev-gui` (`make docker-test-gui`). Quote the counts as printed.
- [ ] 4.4 Push the branch and hand back. Tick these boxes in the same push.

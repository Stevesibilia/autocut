## Why

Two defects from the 2026-09-22 project review (`docs/reviews/2026-09-22-project-review.md`, findings 1 and 3).

- **#70.** `Manifest.load` never looks at `schema_version`, and the model keeps Pydantic's default `extra="ignore"`. A manifest written by a newer build loads without complaint and its unknown fields are dropped. The GUI then autosaves the stripped file over the original without the user doing anything. AGENTS.md promises a migration on every `MANIFEST_SCHEMA_VERSION` bump, but there is nowhere to put one. This is the only finding in the review that can lose user work.
- **#69.** `test_coming_back_selects_the_clip_that_was_playing` fails at random under a full run. The real player keeps playing during `qtbot.wait(50)`, and a position update announces clip 0 again over the test's own announcement. The app is correct; the test is not.

## What Changes

- Loading a manifest whose `schema_version` is greater than `MANIFEST_SCHEMA_VERSION` SHALL fail with a `ManifestVersionError` that names both versions. The file SHALL be left untouched.
- Every load SHALL pass through a migration step that brings an older manifest up to the current version one version at a time. The table of steps is empty while the version is 1.
- The CLI SHALL report a refused manifest as a one-line error and exit with status 1, never a traceback. The GUI SHALL show it in the existing warning dialog on both the open and the new-project paths.
- The flaky test SHALL no longer run the event loop between announcing a clip and returning to the grid.

## Capabilities

### New Capabilities

- `project-manifest`: loading the project file, version checks and migrations.

### Modified Capabilities

None. The GUI and CLI changes only surface the new error through paths that already exist.

## Impact

`autocut/core/manifest.py`, `autocut/cli/main.py`, `autocut/gui/screens/project.py`, `SPEC.md` §9, `CHANGELOG.md`. Tests in `tests/unit/test_manifest.py`, `tests/unit/test_gui_project_screen.py`, `tests/unit/test_gui_review.py` and one CLI test file. No change to the manifest's contents, so no schema bump.

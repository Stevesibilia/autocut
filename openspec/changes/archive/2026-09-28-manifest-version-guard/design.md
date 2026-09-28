## Context

`Manifest.load` (`autocut/core/manifest.py:637`) is `cls.model_validate_json(path.read_text(...))`. It has five production callers:

- CLI: `_open_manifest` (`autocut/cli/main.py:215`, used by `analyze`), `_open_project` (`main.py:235`, used by eight commands), and `report` (`main.py:705`), which loads directly.
- GUI: `ProjectState.new_project` (`autocut/gui/state.py:210`) and `ProjectState.open_project` (`state.py:228`).

On the GUI side, `app.py:546` and `screens/project.py:425` already catch `(FileNotFoundError, ValueError)` around `open_project` and show `QMessageBox.warning`. `screens/project.py:392` catches only `OSError` around `new_project`, so a manifest that fails to validate there crashes the window today. On the CLI side nothing catches a load error.

In the flaky test (`tests/unit/test_gui_review.py:1318`), `play_all()` leaves a real `QMediaPlayer` playing. The test calls `montage._announce(last)` and then `qtbot.wait(50)`. During the wait, `MontagePlayer._position_changed` (`autocut/gui/widgets/montage.py:476`) receives a position near 0. `clip_at` returns clip 0, which differs from `_current_order`, so clip 0 is announced again. `show_grid` (`autocut/gui/screens/review.py:705`) reads `montage.current_segment_id()` synchronously as its first statement, so nothing needs the event loop between the announcement and `show_grid`.

## Decisions

**1. A dedicated error that is a `ValueError`.** Add `class ManifestVersionError(ValueError)` to `autocut/core/manifest.py`. It subclasses `ValueError` so that the GUI's existing `except (FileNotFoundError, ValueError)` handlers show it without change. It carries `found: int` and `supported: int` as attributes. When no version can be read (a `schema_version` that is not an integer, or a top level that is not an object), `found` is `0`: no manifest was ever written with version 0, so the sentinel cannot be mistaken for a real version, and callers read the message, not the attribute (decided during the build). The message is written for the user, with the path, for example:

`/path/manifest.json was saved by a newer AutoCut (manifest schema 2); this build reads up to schema 1. Update AutoCut to open this project.`

**2. Load goes through a dict and `_migrate`.** `Manifest.load` becomes: read the text, `json.loads`, pass the dict to a module-level `_migrate(data, path)`, then `cls.model_validate(data)`. `_migrate`:

- reads `schema_version`. A missing key counts as 1, because version 1 is the only version ever written. A value that is not an `int` (a `bool` counts as not an int) raises `ManifestVersionError` with the message `... has an unreadable schema_version (<repr>)`.
- raises `ManifestVersionError` when the version is greater than `MANIFEST_SCHEMA_VERSION`. The file is only read, never written, so it stays untouched.
- while the version is lower than the current one, applies `_MIGRATIONS[version](data)` and increments. `_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}`, keyed by the version a step migrates _from_. It is empty today. A missing step for a lower version is a programming error: raise `RuntimeError`, not `ManifestVersionError`.
- sets `data["schema_version"] = MANIFEST_SCHEMA_VERSION` and returns `data`.

Reason: the migration table is the place AGENTS.md already promises. Creating it while it is empty keeps the first real migration small.

**3. `extra` stays `"ignore"`.** Rejected: `extra="forbid"`, because it would turn every removed field in an older file into a hard failure, which is the migration step's job. Also rejected: `extra="allow"`, because keeping unknown fields would suggest a newer file is safe to edit. It is not: fields it knows about may have changed meaning.

**4. The CLI reports and exits.** Add a helper `_load_manifest(path: Path) -> Manifest` in `autocut/cli/main.py`. It calls `Manifest.load`, catches `ManifestVersionError`, prints `[red]Cannot open the project[/red]: {error}` through `console`, and raises `typer.Exit(code=1)`. `_open_manifest`, `_open_project` and `report` call it instead of `Manifest.load`. Only `ManifestVersionError` is caught. A corrupt manifest still raises as it does today; that is out of scope.

**5. The GUI covers the new-project path.** In `autocut/gui/screens/project.py:392`, `except OSError` becomes `except (OSError, ValueError)`, with the same `"Cannot use that folder"` dialog. `new_project` loads the manifest before assigning `self.manifest`, so a refused file leaves the state unchanged and no autosave can overwrite it. The test must prove that. `app.py` and the open path need no change.

**6. The flaky test drops the wait.** In `test_coming_back_selects_the_clip_that_was_playing`, remove `qtbot.wait(50)` and extend the comment above `_announce` with one sentence on why no wait may follow: the real player is still playing, and the next position update would announce clip 0 again (#69). No production code changes for #69.

**7. Docs.** In `SPEC.md` §9 (line 413), after "The schema is versioned.", add: "A manifest from a newer schema is refused rather than loaded and rewritten, and an older one is brought up to date one version at a time by a migration step on load." Add one line to `CHANGELOG.md` under `## [Unreleased]` → `### Fixed`.

## Not touched

- The manifest's fields and `MANIFEST_SCHEMA_VERSION`: no bump.
- `ANALYSIS_SCHEMA_VERSION` and the analysis cache (`autocut/core/cache.py`), which has its own version check.
- `autocut/gui/widgets/montage.py` and `review.py`: the app behaviour behind #69 is correct.
- Error handling for corrupt or invalid manifests beyond the GUI `new_project` catch in decision 5.

## Risks / Trade-offs

- **A test that relies on `Manifest.load` accepting a manifest with no `schema_version`, or with `schema_version` as a string.** Decision 2 accepts the first and rejects the second. If an existing test or fixture breaks on the string case, report it; do not loosen the check.
- **Removing the wait breaks the test in a way other than the flake**, for example `preview.title` not yet updated. `show_segment` looks synchronous. If it is not, report what the test needs; do not put back a timed wait.
- **mypy strict on `json.loads`.** It returns `Any`. Narrow it with an `isinstance(data, dict)` check. A top level that is not an object raises `ManifestVersionError("... is not a manifest")`.

## Migration Plan

None. The version stays 1.

## Open Questions

None.

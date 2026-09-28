## Context

Measured on 2026-09-28 against live PyPI and the dev venv (`.venv`, Python 3.14.7):

- The venv runs `opencv-python-headless` 5.0.0.93 **and** `opencv-python` 5.0.0.93 (pulled by scenedetect 0.7.1, whose `requires_dist` lists `opencv-python` unconditionally), librosa 1.0.0 (`requires_python >=3.12`, `numpy>=2.1`), numpy 2.5.2, mypy 2.3.1, ruff 0.16.6, pytest 9.
- scenedetect is imported in one place, lazily: `detect_shots_pyscenedetect` (`autocut/core/segment.py:82`), used only when `analysis.detector = "pyscenedetect"` (`autocut/core/config.py:61`, default `"inmemory"`). No test references it.
- `ruff check --target-version py312 --select UP` finds three sites: `autocut/core/config.py:24` (UP046, `PerClass(BaseModel, Generic[T])`), `autocut/gui/models.py:58` (UP040, `AnyIndex`), `autocut/gui/widgets/chips.py:135` (UP040, `Chip`).
- `Dockerfile.dev` already installs `libgl1` and `libglib2.0-0`. The `ai` stage pins `torch==2.13.0+cpu` and `torchvision==0.28.0+cpu`. The PyTorch CPU index has `torch-2.14.0+cpu` for cp312, cp313 and cp314 on `manylinux_2_28_x86_64` and `torchvision-0.29.0+cpu` for cp312.
- Latest action releases: `actions/checkout` v7.0.1, `actions/setup-python` v7.0.0, `softprops/action-gh-release` v3.0.3, `docker/bake-action` v7.4.0, `docker/setup-buildx-action` v4.4.1.
- `uv` 0.12.19 is 3 days old on 2026-09-28, so it is not yet eligible under the 5-day rule.
- `release.yml` has no `permissions` and no `tag_name`. A `workflow_dispatch` run from a branch therefore cannot create a release.

## Decisions

**1. Python 3.12 floor.** `requires-python = ">=3.12"`, `[tool.ruff] target-version = "py312"`. `[tool.mypy] python_version = "3.12"` stays, and its comment is rewritten, because the reason (numpy stubs parse only at 3.12) now coincides with the floor. Fix the three UP sites the way ruff proposes: `class PerClass[T](BaseModel)` and `type AnyIndex = ...` / `type Chip = ...`. If a `type` alias breaks runtime use (an `isinstance`, a `get_args`, a Qt signal signature), or pydantic rejects the PEP 695 generic, keep the old form with `# noqa: UP040` (or `UP046`) and a one-line reason, and report it. Reason: 3.11 can no longer resolve the same numpy and librosa majors as the other interpreters. Its end of life is 2027-10.

**2. Floors.** Raise every floor in `pyproject.toml` to the newest release that is at least 5 days old on the day you build. Check each one with `curl -s https://pypi.org/pypi/<pkg>/json` and look at the upload time. Expected values on 2026-09-28, shown so you can spot a surprise:

| Package                  | Floor                           |
| ------------------------ | ------------------------------- |
| hatchling (build-system) | `>=1.32`                        |
| numpy                    | `>=2.4`                         |
| opencv-python-headless   | `>=5.0`                         |
| librosa                  | `>=1.0`                         |
| pydantic                 | `>=2.13`                        |
| pydantic-settings        | `>=2.15`                        |
| typer                    | `>=0.27`                        |
| rich                     | `>=15.0`                        |
| httpx                    | `>=0.28`                        |
| keyring                  | `>=25.7`                        |
| platformdirs             | `>=4.11`                        |
| pillow                   | `>=12.0`                        |
| jinja2                   | `>=3.1.6`                       |
| torch / torchvision      | `>=2.14,<2.15` / `>=0.29,<0.30` |
| open_clip_torch          | `>=3.3,<3.4` (unchanged)        |
| PySide6                  | `>=6.11.2,<6.12` (unchanged)    |
| pytest / pytest-cov      | `>=9.1` / `>=7.1`               |
| ruff                     | `>=0.16`                        |
| mypy                     | `>=2.3`                         |
| pytest-qt                | `>=4.5` (unchanged)             |
| pyinstaller              | `>=6.22`                        |

The numpy floor is 2.4, not 2.5, so that a user on an older distribution package is not forced forward for nothing. The lock file pins the actual version. Drop `types-Pillow`, because Pillow ships its own type hints. Add `uv` to the `dev` extra with the newest eligible floor (`>=0.12`), because `make lock` needs it and the host must not get global installs. Rewrite the torch and PySide6 comments so they state the new facts and drop the "one day old" wording. Keep the lockstep explanation.

**3. scenedetect becomes an extra.** Remove `scenedetect` from `[project.dependencies]` and add `scenedetect = ["scenedetect>=0.7.1"]` to `[project.optional-dependencies]`, with a comment: it is for the validation detector only, and it pulls `opencv-python` next to `opencv-python-headless`. In `detect_shots_pyscenedetect`, wrap the import:

```python
try:
    from scenedetect import ContentDetector, detect  # noqa: PLC0415
except ImportError as exc:
    raise RuntimeError(
        'analysis.detector = "pyscenedetect" needs the scenedetect extra: '
        "pip install 'autocut[scenedetect]'"
    ) from exc
```

Add a unit test that monkeypatches `sys.modules["scenedetect"] = None` and asserts the message. Rejected: switching the core dependency to `opencv-python`. That drags the GUI build of OpenCV (with its own Qt plugins on Linux) into every install and into the PyInstaller bundle, to serve a detector that is off by default.

**4. `constraints.txt` via uv.** Add a `lock` target to the `Makefile`:

```make
lock:
	$(VENV)/bin/uv pip compile pyproject.toml --universal --python-version 3.12 \
	  --extra dev --extra gui --extra dev-gui --extra build --extra scenedetect \
	  --exclude-newer "$$($(PY) -c 'import datetime as d; print((d.datetime.now(d.UTC) - d.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))')" \
	  --no-emit-package autocut --no-header -o constraints.txt
```

Amended at review: `--no-header` was added because the uv header records the `--exclude-newer` timestamp, which moves on every run, so two runs over an unchanged resolution differed in that one line.

If `--no-emit-package autocut` is not needed or not accepted, drop it and say so. `--exclude-newer` enforces the 5-day rule mechanically. The `ai` extra is left out on purpose: torch comes from the CPU index in Docker and from PyPI on macOS, which one universal file cannot express. Its versions are pinned in `pyproject.toml` and `Dockerfile.dev`. Commit the generated `constraints.txt`.
Every install goes through it: `make venv` becomes `$(PY) -m pip install -c constraints.txt -e ".[dev,gui,dev-gui]"`, the Dockerfile's `pip install` lines add `-c constraints.txt` (copy the file into the image next to `pyproject.toml`), and CI's install step does the same.
Rejected: `uv.lock` with `uv sync`. It would move the whole project to uv's workflow and change every command in AGENTS.md. A constraints file keeps pip and gives the same pinning.

**5. CI (`.github/workflows/ci.yml`).**

- Top-level `permissions: contents: read`.
- `actions/checkout@v7` and `actions/setup-python@v7` everywhere.
- Rewrite the header comment: the repository is public and minutes are free, so the pull request matrix runs the oldest and newest interpreters. Keep the reasons for path filters and skipping pushes to main.
- Matrix: `github.event_name == 'pull_request' && '["3.12", "3.14"]' || '["3.12", "3.13", "3.14"]'`.
- Install: `pip install -c constraints.txt -e ".[dev]"`.
- After installing ffmpeg: a step `ffmpeg -hide_banner -version | head -1`.
- Tests: on the 3.12 leg only, `pytest -q --cov=autocut.core --cov=autocut.cli --cov-report=term --cov-fail-under=<N>`, where N is the whole-number coverage you measure locally for the same scope, minus 2. Record the measured value in the hand-back. The other legs run `pytest -q`. The scope excludes `autocut/gui` because this job installs no Qt.
- New job `audit` on `ubuntu-latest`: checkout, setup-python 3.12, `pip install -c constraints.txt -e ".[dev,scenedetect]" pip-audit`, `pip-audit --skip-editable`. It fails the run on a known vulnerability. That is the point: a finding is then a deliberate, visible decision.
- The `ai` and `gui` jobs build through `docker/setup-buildx-action@v4` and `docker/bake-action@v7` with `files: compose.yaml`, `targets: dev-ai` (or `dev-gui`), `load: true`, and `set: |` `*.cache-from=type=gha,scope=<target>` / `*.cache-to=type=gha,mode=max,scope=<target>`. They then run `docker compose run --rm ...` as today. The image bake loads must carry the name compose expects, so compose does not rebuild it. Verify this on the pull request's first CI run: the "Build" step of a second run must report cached layers. If bake and compose disagree on the image name, set `image:` on the service in `compose.yaml`. Amended at review: they do disagree. The implementer found that bake tags a compose target with no `image:` as `autocut-<service>`, while compose tags it with the directory name (`autocut-79-dev`). So every service now carries `image: autocut-<service>`.

**6. Docker.** Keep `python:3.12-slim`, because the image tests the floor, and pin it by digest (`python:3.12-slim@sha256:<digest>`). Read the digest with `docker buildx imagetools inspect python:3.12-slim`. The `ai` stage installs `torch==2.14.0+cpu` and `torchvision==0.29.0+cpu`.

**7. Dependabot.** New `.github/dependabot.yml`, version 2, with two updates, `github-actions` (directory `/`) and `docker` (directory `/`). Both weekly, both with `cooldown: default-days: 5`, and both with `commit-message: prefix: "ci"` and `prefix: "build"` respectively. No pip entry: the constraints file is refreshed with `make lock`.

**8. `release.yml`.**

- `on: workflow_dispatch` with input `tag` (required, string, description `Tag to create, e.g. v0.6.0`).
- `permissions: contents: write`.
- `runs-on: macos-15`.
- checkout@v7 and setup-python@v7.
- Before `make dmg`: `ruff check .`, `mypy autocut`, `python scripts/make_fixtures.py`, `pytest -q`. Install `-c constraints.txt -e ".[gui,ai,build,dev,dev-gui]"`.
- `softprops/action-gh-release@v3` with `tag_name: ${{ inputs.tag }}`, `target_commitish: ${{ github.sha }}`.

The header comment still says the workflow stays manual until M6.

**9. ADR 11.** `docs/adr/0011-python-312-and-locked-dependencies.md`, in the Nygard format of the others (Status: Accepted, date 2026-09-28). It covers decisions 1, 3 and 4 and their rejected alternatives. It supersedes the "pin when the PyInstaller work starts" line in AGENTS.md: the lock arrives now, because unbounded floors let three majors in without review.

**10. Docs.**

- `README.md:13`: Python 3.12 or newer.
- `SPEC.md:91`: Python 3.12 or newer, and CI tests 3.12, 3.13 and 3.14.
- `SPEC.md` §7.2 or wherever the pyscenedetect detector is described: note that it needs the `scenedetect` extra.
- `AGENTS.md`:
  - line 9: Python 3.12+, with the extras list gaining `scenedetect`;
  - line 38: target `py312`;
  - Dependency Safety rule 3: "Python 3.12 through 3.14";
  - the "Package Management" section: installs go through `constraints.txt`, and `make lock` regenerates it after any change to `pyproject.toml`; replace "There is no lock file yet" with that;
  - the CI table row for `ci.yml`: 3.12 and 3.14 per PR, 3.12/3.13/3.14 on dispatch, coverage gate, audit job;
  - the `release.yml` row: "manual dispatch with a tag input".
- `CHANGELOG.md` under `[Unreleased]`, in `### Changed`: Python 3.12 floor, scenedetect extra, constraints file; in `### Removed`: Python 3.11 support.

## Not touched

- The GUI-planned wording and the other AGENTS.md drift from issue #83, apart from the lines named in decision 10.
- `autocut/core` behaviour, apart from `segment.py` (decision 3) and the `config.py:24` generic syntax (decision 1).
- Code signing and notarization (M6).

## Risks / Trade-offs

- **Conflict with the pipeline-robustness branch (#78).** It changes `PerClass`'s base class in `config.py`, on the same line as decision 1. Whichever merges second rebases and takes both: `class PerClass[T](_Strict)`. Expected, not a problem.
- **OpenCV 5 or librosa 1.0 change a metric or a beat grid.** The synthetic tests may not see it. The user runs the real-footage check before merge (ADR 8). If a unit test fails on a numeric tolerance after the upgrade, report the numbers. Do not widen the tolerance.
- **`pip-audit` finds something today.** Report the advisory ids. Do not add ignores without asking.
- **bake's GHA cache or the image naming does not work as described.** Report what the CI run printed. Falling back to plain `docker compose build` with no cache is acceptable if you say so.
- **`uv pip compile --universal` cannot resolve** because a pinned wheel is missing for a platform: report the resolver output.

## Migration Plan

Developers run `make venv` again, because the old venv carries scenedetect and opencv-python. No data migration.

## Open Questions

None.

## Why

Issue #79, from the 2026-09-28 project review. The dependency floors in `pyproject.toml` are open-ended and far behind, and there is no lock file. As a result three new major versions reached the dev venv without review: OpenCV 5, scenedetect 0.7 and librosa 1.0. scenedetect 0.7 hard-requires `opencv-python`, so two `cv2` distributions are now installed side by side. numpy 2.5 and librosa 1.0 need Python 3.12, so the 3.11 CI job and the 3.12+ jobs already test different majors. CI uses actions on the deprecated Node 20 runtime and has no coverage gate, dependency audit or update bot. `release.yml` cannot publish a release as written.

The user decided on 2026-09-28 to accept the new majors, lock them, and drop Python 3.11.

## What Changes

- `requires-python` becomes `>=3.12`. ruff targets `py312`. CI tests 3.12 and 3.14 on every pull request and 3.12, 3.13 and 3.14 on manual dispatch.
- Every dependency floor is raised to the newest release that is at least 5 days old. `types-Pillow` is dropped. torch and torchvision move to 2.14 and 0.29.
- scenedetect moves from the core dependencies to a new optional extra, `scenedetect`, because only the non-default `analysis.detector = "pyscenedetect"` uses it. The default install then carries a single `cv2`, `opencv-python-headless`.
- A generated `constraints.txt` pins every transitive version for the dev, gui, dev-gui, build and scenedetect extras. `make lock` regenerates it with uv, excluding releases newer than 5 days. The venv, the Docker images and CI install through it.
- CI moves to `actions/checkout@v7` and `actions/setup-python@v7`, declares read-only permissions, logs the ffmpeg version, adds a coverage gate and a `pip-audit` job, and caches Docker layers. Dependabot watches GitHub Actions and the Docker base image with a 5-day cooldown.
- `release.yml` gets `contents: write`, a required tag input, `softprops/action-gh-release@v3`, a `macos-15` runner, and lint and tests before the build.
- ADR 11 records the Python floor, the lock file and the scenedetect extra.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `segmentation`: the PySceneDetect validation detector needs the `scenedetect` extra and says so when it is missing. The rest of the change is packaging, CI and the development environment, with no behaviour to specify.

## Impact

`pyproject.toml`, `constraints.txt` (new), `Makefile`, `Dockerfile.dev`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/dependabot.yml` (new), `docs/adr/0011-python-312-and-locked-dependencies.md` (new), `autocut/core/segment.py`, three type-alias sites for ruff `py312`, `README.md`, `SPEC.md`, `AGENTS.md`, `CHANGELOG.md`. Merging requires a real-footage check by the user (ADR 8), because OpenCV 5 and librosa 1.0 feed metrics and beat tracking.

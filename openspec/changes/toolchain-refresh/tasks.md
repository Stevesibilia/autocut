## 1. Python 3.12 floor, dependency floors, scenedetect extra (design decisions 1, 2, 3), one commit

- [x] 1.1 `pyproject.toml`: `requires-python`, ruff target, mypy comment, every floor from decision 2 checked live on PyPI, `types-Pillow` dropped, `uv` added to `dev`, the `scenedetect` extra, and rewritten torch and PySide6 comments.
- [x] 1.2 The three UP sites (decision 1) and the guarded import in `autocut/core/segment.py` (decision 3), with its unit test in `tests/unit/test_segment.py` (or the closest existing segment test file).
- [x] 1.3 Rebuild the venv from scratch (`rm -rf .venv && make venv`), then `.venv/bin/pip list | grep -iE 'opencv|scenedetect'` must show `opencv-python-headless` only. Put the output in the hand-back.
- [x] 1.4 Commit: `build: require python 3.12 and raise dependency floors`.

## 2. Constraints file (decision 4), one commit

- [x] 2.1 `make lock` target, generated `constraints.txt`, `make venv` and the Dockerfile installs going through it.
- [x] 2.2 Run `make lock` twice. The second run must produce no diff. Rebuild the venv with `make venv` and run `make lint`.
- [x] 2.3 Commit: `build: lock dependencies in a constraints file`.

## 3. Docker (decision 6), one commit

- [x] 3.1 Base image pinned by digest; torch and torchvision 2.14.0/0.29.0 CPU pins.
- [x] 3.2 `make docker-test` and `make docker-test-gui` pass (hand them to the test runner). `make docker-test-ai` is optional locally, because CI runs it; say whether you ran it.
- [x] 3.3 Commit: `build(docker): pin the base image and move to torch 2.14`.

## 4. CI, Dependabot, release (decisions 5, 7, 8), one commit

- [x] 4.1 `ci.yml`, `.github/dependabot.yml`, `release.yml` as specified.
- [x] 4.2 Measure local coverage for `autocut.core` and `autocut.cli` (`.venv/bin/pytest -q --cov=autocut.core --cov=autocut.cli --cov-report=term | tail -3`) and set `--cov-fail-under` to that number minus 2.
- [x] 4.3 Check the YAML with `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" <files>` from the venv, or with `actionlint` if it is already on the host. Do not install it.
- [x] 4.4 Commit: `ci: refresh actions, add coverage gate, audit and layer cache`.

## 5. ADR and docs (decisions 9, 10), one commit

- [x] 5.1 ADR 11, `README.md`, `SPEC.md`, `AGENTS.md`, `CHANGELOG.md`, each Markdown file formatted with `sjust format-md <path>`.
- [x] 5.2 Commit: `docs: record the python 3.12 floor and the constraints file`.

## 6. Gates and hand-back

- [x] 6.1 `make lint` and `openspec validate toolchain-refresh --strict`.
- [x] 6.2 `make test` through the test runner. Quote the counts.
- [x] 6.3 Real run: `autocut analyze tests/fixtures/synthetic --out <tmpdir>` completes on the new venv. Put its summary lines in the hand-back.
- [x] 6.4 Tick these boxes, push the branch and hand back. CI runs on the pull request the architect opens. The bake cache check in decision 5 is verified there, by the architect.

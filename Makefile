.PHONY: venv test lint fixtures docker-test docker-test-ai docker-test-gui dmg lock

VENV ?= .venv
PY := $(VENV)/bin/python

venv:
	python3 -m venv $(VENV)
	$(PY) -m pip install -c constraints.txt -e ".[dev,gui,dev-gui]"

# Regenerates constraints.txt with uv. Run after any change to pyproject.toml.
# Every install (venv, Docker, CI) then goes through the pinned file. No header, so
# an unchanged resolution gives no diff: the header would carry the moving
# --exclude-newer date (now minus 5 days, the dependency safety rule).
lock:
	$(VENV)/bin/uv pip compile pyproject.toml --universal --python-version 3.12 \
	  --extra dev --extra gui --extra dev-gui --extra build --extra scenedetect \
	  --exclude-newer "$$($(PY) -c 'import datetime as d; print((d.datetime.now(d.UTC) - d.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))')" \
	  --no-emit-package autocut --no-header -o constraints.txt

fixtures:
	$(PY) scripts/make_fixtures.py

lint:
	$(VENV)/bin/ruff check . && $(VENV)/bin/ruff format --check . && $(VENV)/bin/mypy autocut

test: fixtures
	$(VENV)/bin/pytest -q

docker-test:
	docker compose run --rm dev sh -c "python scripts/make_fixtures.py && pytest -q"

# The tests marked "ai" only. Builds a second image with the ai extra and keeps the
# model weights in a named volume, so the checkpoint is downloaded once.
docker-test-ai:
	docker compose run --rm dev-ai sh -c "python scripts/make_fixtures.py && pytest -q -m ai"

# The tests marked "gui" only. Builds a third image with the gui extra and the Qt
# system libraries, and runs Qt offscreen.
docker-test-gui:
	docker compose run --rm dev-gui sh -c "python scripts/make_fixtures.py && pytest -q -m gui"

# macOS only. Requires the build extra and ffmpeg on PATH. See ADR 7.
dmg:
	@echo "PyInstaller spec lands with milestone M6. See docs/adr/0007-pyinstaller-macos-bundle.md."
	@exit 1

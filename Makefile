.PHONY: venv test lint fixtures docker-test dmg

VENV ?= .venv
PY := $(VENV)/bin/python

venv:
	python3 -m venv $(VENV)
	$(PY) -m pip install -e ".[dev,gui]"

fixtures:
	$(PY) scripts/make_fixtures.py

lint:
	$(VENV)/bin/ruff check . && $(VENV)/bin/ruff format --check . && $(VENV)/bin/mypy autocut

test: fixtures
	$(VENV)/bin/pytest -q

docker-test:
	docker compose run --rm dev sh -c "python scripts/make_fixtures.py && pytest -q"

# macOS only. Requires the build extra and ffmpeg on PATH. See ADR 7.
dmg:
	@echo "PyInstaller spec lands with milestone M6. See docs/adr/0007-pyinstaller-macos-bundle.md."
	@exit 1

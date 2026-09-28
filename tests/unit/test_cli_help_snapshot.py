"""``--help`` for the root command and every subcommand, pinned before the CLI split.

core-consolidation task 5 turns ``autocut/cli/main.py`` into a package of modules.
This snapshot is what proves the split changed no registration and no help text: a
difference here is fixed in the code, never in the fixture (design Risks).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer import rich_utils
from typer.testing import CliRunner

from autocut.cli.main import app

runner = CliRunner()

SNAPSHOT_PATH = Path(__file__).parent.parent / "fixtures" / "cli_help_snapshot.json"
SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render help as on a plain terminal wherever the test runs.

    Typer decides at import time to force terminal rendering when ``GITHUB_ACTIONS``,
    ``FORCE_COLOR`` or ``PY_COLORS`` is set, so the same help came out styled in CI and
    plain locally, and the snapshot only matched one of them.
    """
    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", None)


@pytest.mark.parametrize("key", sorted(SNAPSHOT))
def test_help_is_unchanged_by_the_cli_split(key: str) -> None:
    args = [] if key == "(root)" else key.split(" ")
    result = runner.invoke(app, [*args, "--help"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout == SNAPSHOT[key]

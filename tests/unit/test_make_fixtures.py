"""The fixture generator has to survive several test runs starting at once.

``make test`` on the host and ``make docker-test`` in a container both call
``scripts/make_fixtures.py``, and three of those regenerating the same directory once
hung a container. The tests here pin the two properties that prevent it: a complete set
is left alone, and an incomplete one is built somewhere else and moved in, so no reader
ever opens a half written file. ffmpeg is never invoked; ``build`` is replaced.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_fixtures.py"


@pytest.fixture(scope="module")
def make_fixtures() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_fixtures", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_fixtures"] = module
    spec.loader.exec_module(module)
    return module


def write_all(module: ModuleType, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in module.EXPECTED:
        (directory / name).write_bytes(b"x")


def test_complete_needs_every_file_non_empty(make_fixtures: ModuleType, tmp_path: Path) -> None:
    assert not make_fixtures.complete(tmp_path)
    write_all(make_fixtures, tmp_path)
    assert make_fixtures.complete(tmp_path)
    (tmp_path / make_fixtures.EXPECTED[0]).write_bytes(b"")
    assert not make_fixtures.complete(tmp_path)


def test_complete_set_is_not_rebuilt(
    make_fixtures: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "synthetic"
    write_all(make_fixtures, out)
    monkeypatch.setattr(make_fixtures, "OUT", out)
    monkeypatch.setattr(make_fixtures, "build", lambda _dir: pytest.fail("rebuilt a full set"))

    assert make_fixtures.main([]) == 0


def test_force_rebuilds_a_complete_set(
    make_fixtures: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "synthetic"
    write_all(make_fixtures, out)
    monkeypatch.setattr(make_fixtures, "OUT", out)
    monkeypatch.setattr(make_fixtures, "build", lambda work: write_all(make_fixtures, work))

    assert make_fixtures.main(["--force"]) == 0


def test_files_are_built_elsewhere_and_moved_in(
    make_fixtures: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "synthetic"
    monkeypatch.setattr(make_fixtures, "OUT", out)
    seen: list[Path] = []

    def build(work: Path) -> None:
        seen.append(work)
        # Nothing may reach OUT while the set is incomplete.
        assert list(out.iterdir()) == []
        write_all(make_fixtures, work)

    monkeypatch.setattr(make_fixtures, "build", build)

    assert make_fixtures.main([]) == 0
    assert seen and seen[0] != out
    assert make_fixtures.complete(out)
    assert list(out.parent.glob(".synthetic-*")) == []


def test_a_failed_build_leaves_no_temporary_directory(
    make_fixtures: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "synthetic"
    monkeypatch.setattr(make_fixtures, "OUT", out)

    def build(work: Path) -> None:
        (work / make_fixtures.EXPECTED[0]).write_bytes(b"x")
        raise RuntimeError("ffmpeg died")

    monkeypatch.setattr(make_fixtures, "build", build)

    with pytest.raises(RuntimeError):
        make_fixtures.main([])
    assert list(out.parent.glob(".synthetic-*")) == []
    assert not make_fixtures.complete(out)

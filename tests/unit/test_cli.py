from typer.testing import CliRunner

from autocut import __version__
from autocut.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("analyze", "select", "soundtrack", "report", "sync", "export", "run"):
        assert cmd in result.stdout


def test_unimplemented_stage_exits_2(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Stages that land in later milestones say so rather than failing obscurely.

    ``soundtrack`` left this list when m4-soundtrack-prompt implemented it; ``sync`` is
    the last stub and goes with m4-beat-sync.
    """
    result = runner.invoke(app, ["sync", str(tmp_path), "--audio", str(tmp_path / "track.mp3")])
    assert result.exit_code == 2
    assert "not implemented" in result.stdout


def test_soundtrack_needs_a_project(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """It is implemented now, so a missing manifest is what fails rather than the stage."""
    result = runner.invoke(app, ["soundtrack", str(tmp_path / "nowhere")])
    assert result.exit_code == 1
    assert "No manifest found" in result.stdout

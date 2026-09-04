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


def test_every_command_is_implemented() -> None:
    """m4-beat-sync implemented sync, the last stub, so nothing prints a stage notice."""
    from autocut.cli import main

    assert not hasattr(main, "_not_implemented")


def test_soundtrack_needs_a_project(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """It is implemented now, so a missing manifest is what fails rather than the stage."""
    result = runner.invoke(app, ["soundtrack", str(tmp_path / "nowhere")])
    assert result.exit_code == 1
    assert "No manifest found" in result.stdout


def test_sync_needs_a_project(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = runner.invoke(
        app, ["sync", str(tmp_path / "nowhere"), "--audio", str(tmp_path / "track.wav")]
    )
    assert result.exit_code == 1
    assert "No manifest found" in result.stdout

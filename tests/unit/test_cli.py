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
    """Stages that land in later milestones say so rather than failing obscurely."""
    for stage in ("soundtrack", "sync"):
        args = [stage, str(tmp_path)]
        if stage == "sync":
            args += ["--audio", str(tmp_path / "track.mp3")]
        result = runner.invoke(app, args)
        assert result.exit_code == 2, stage

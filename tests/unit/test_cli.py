from pathlib import Path

import pytest
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


def test_config_flag_needs_an_existing_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["report", str(tmp_path / "project"), "--config", str(tmp_path / "typo.toml")]
    )
    assert result.exit_code == 1
    assert "Configuration not found" in result.stdout
    assert str(tmp_path / "typo.toml") in result.stdout


def test_a_toml_syntax_error_is_one_line(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    toml.write_text("this is not valid toml [[[", encoding="utf-8")

    result = runner.invoke(app, ["report", str(tmp_path / "project"), "--config", str(toml)])

    assert result.exit_code == 1
    assert "Cannot read the configuration" in result.stdout
    assert "Traceback" not in result.stdout


def test_an_unknown_configuration_key_is_one_line(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    toml.write_text("[analysis]\nsample_fsp = 3\n", encoding="utf-8")

    result = runner.invoke(app, ["report", str(tmp_path / "project"), "--config", str(toml)])

    assert result.exit_code == 1
    assert "Cannot read the configuration" in result.stdout
    assert "Traceback" not in result.stdout


def test_a_manifest_that_is_not_json_is_one_line(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "manifest.json").write_text("not json", encoding="utf-8")

    result = runner.invoke(app, ["report", str(project)])

    assert result.exit_code == 1
    assert "Cannot open the project" in result.stdout
    assert "Traceback" not in result.stdout


@pytest.mark.ffmpeg
def test_analyze_reports_a_missing_ffprobe_once(
    synthetic_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil as shutil_module

    real_which = shutil_module.which
    monkeypatch.setattr(
        shutil_module, "which", lambda name: None if name == "ffprobe" else real_which(name)
    )

    result = runner.invoke(app, ["analyze", str(synthetic_dir), "--out", str(tmp_path / "out")])

    assert result.exit_code == 1
    assert result.stdout.count("Missing tool") == 1
    assert "ffprobe" in result.stdout
    assert "Traceback" not in result.stdout

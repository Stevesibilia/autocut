"""The analyze command: manifest written, empty folder refused, flags mapped onto config."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core.manifest import Manifest

runner = CliRunner()


def test_analyze_help_lists_the_ingest_flags() -> None:
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    for flag in ("--no-proxies", "--workers", "--out", "--no-cloud"):
        assert flag in result.stdout


def test_analyze_on_an_empty_folder_exits_non_zero(tmp_path: Path) -> None:
    empty = tmp_path / "footage"
    empty.mkdir()
    result = runner.invoke(app, ["analyze", str(empty), "--out", str(tmp_path / "edit")])
    assert result.exit_code != 0
    assert "No video files found" in result.stdout


@pytest.mark.ffmpeg
def test_analyze_writes_a_valid_manifest(synthetic_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    result = runner.invoke(
        app,
        ["analyze", str(synthetic_dir), "--out", str(out), "--workers", "2"],
    )
    assert result.exit_code == 0, result.stdout

    manifest_path = out / "manifest.json"
    assert manifest_path.exists()
    manifest = Manifest.load(manifest_path)
    assert len(manifest.files) == len(list(synthetic_dir.glob("*.mp4")))
    assert manifest.output_dir == out
    assert manifest.config_snapshot["analysis"]["workers"] == 2
    for source in manifest.files.values():
        assert source.id
        assert source.source_class
        assert source.class_signal


@pytest.mark.ffmpeg
def test_analyze_updates_an_existing_manifest(synthetic_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    args = ["analyze", str(synthetic_dir), "--out", str(out), "--workers", "1"]
    assert runner.invoke(app, args).exit_code == 0
    created_at = Manifest.load(out / "manifest.json").created_at

    assert runner.invoke(app, [*args, "--no-proxies"]).exit_code == 0
    again = Manifest.load(out / "manifest.json")
    assert again.created_at == created_at
    assert again.updated_at >= created_at
    assert again.config_snapshot["analysis"]["use_proxies"] is False

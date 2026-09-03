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


def config_file(tmp_path: Path) -> Path:
    """A config that keeps the analysis cache inside the test's own directory."""
    toml = tmp_path / "autocut.toml"
    toml.write_text(f'[cache]\ndir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    return toml


@pytest.mark.ffmpeg
def test_analyze_writes_a_valid_manifest(synthetic_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    result = runner.invoke(
        app,
        [
            "analyze",
            str(synthetic_dir),
            "--out",
            str(out),
            "--workers",
            "2",
            "--config",
            str(config_file(tmp_path)),
        ],
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

    assert manifest.segments
    scored_files = {segment.file_id for segment in manifest.segments.values()}
    assert scored_files == set(manifest.files)
    for segment in manifest.segments.values():
        assert segment.score is not None
        assert segment.metrics is not None
        assert segment.thumbnail is not None and segment.thumbnail.exists()


@pytest.mark.ffmpeg
def test_second_analyze_run_reports_cache_hits(synthetic_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    args = [
        "analyze",
        str(synthetic_dir),
        "--out",
        str(out),
        "--workers",
        "2",
        "--config",
        str(config_file(tmp_path)),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout
    assert "(0 files from cache)" in first.stdout

    count = len(list(synthetic_dir.glob("*.mp4")))
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout
    assert f"({count} files from cache)" in second.stdout


@pytest.mark.ffmpeg
def test_analyze_updates_an_existing_manifest(synthetic_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    args = [
        "analyze",
        str(synthetic_dir),
        "--out",
        str(out),
        "--workers",
        "1",
        "--config",
        str(config_file(tmp_path)),
    ]
    assert runner.invoke(app, args).exit_code == 0
    created_at = Manifest.load(out / "manifest.json").created_at

    assert runner.invoke(app, [*args, "--no-proxies"]).exit_code == 0
    again = Manifest.load(out / "manifest.json")
    assert again.created_at == created_at
    assert again.updated_at >= created_at
    assert again.config_snapshot["analysis"]["use_proxies"] is False


def test_report_on_a_folder_without_a_manifest_exits_non_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["report", str(tmp_path)])
    assert result.exit_code != 0
    assert "No manifest found" in result.stdout


@pytest.mark.ffmpeg
def test_analyze_writes_the_report_next_to_the_manifest(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "edit"
    result = runner.invoke(
        app,
        [
            "analyze",
            str(synthetic_dir),
            "--out",
            str(out),
            "--workers",
            "2",
            "--config",
            str(config_file(tmp_path)),
        ],
    )
    assert result.exit_code == 0, result.stdout
    report = out / "report.html"
    assert report.exists()
    assert (out / "manifest.json").exists()
    html = report.read_text(encoding="utf-8")
    assert "http://" not in html
    assert "https://" not in html
    assert "thumbs/" in html


@pytest.mark.ffmpeg
def test_report_command_rerenders_from_an_existing_manifest(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "edit"
    analyze_args = [
        "analyze",
        str(synthetic_dir),
        "--out",
        str(out),
        "--workers",
        "2",
        "--config",
        str(config_file(tmp_path)),
    ]
    assert runner.invoke(app, analyze_args).exit_code == 0
    (out / "report.html").unlink()

    result = runner.invoke(app, ["report", str(out)])
    assert result.exit_code == 0, result.stdout
    assert (out / "report.html").exists()
    assert "Report written to" in result.stdout

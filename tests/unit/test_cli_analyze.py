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


def test_select_without_a_manifest_exits_non_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["select", str(tmp_path)])
    assert result.exit_code != 0
    assert "No manifest found" in result.stdout


def test_select_help_lists_the_overrides() -> None:
    result = runner.invoke(app, ["select", "--help"])
    assert result.exit_code == 0
    for flag in ("--max-clips", "--duration", "--diversity"):
        assert flag in result.stdout


@pytest.mark.ffmpeg
def test_select_after_analyze_stays_within_the_caps(synthetic_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    assert (
        runner.invoke(
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
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app, ["select", str(out), "--max-clips", "3", "--config", str(config_file(tmp_path))]
    )
    assert result.exit_code == 0, result.stdout

    manifest = Manifest.load(out / "manifest.json")
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    assert 0 < len(selected) <= 3
    assert manifest.selection.max_clips == 3
    assert sorted(s.order for s in selected) == list(range(1, len(selected) + 1))
    for segment in selected:
        assert segment.best_center_s is not None
        assert segment.target_duration_s is not None


@pytest.mark.ffmpeg
def test_a_second_select_with_another_diversity_changes_the_set(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "edit"
    toml = config_file(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "analyze",
                str(synthetic_dir),
                "--out",
                str(out),
                "--workers",
                "2",
                "--config",
                str(toml),
            ],
        ).exit_code
        == 0
    )

    runner.invoke(app, ["select", str(out), "--diversity", "0", "--config", str(toml)])
    first = Manifest.load(out / "manifest.json")
    greedy = {s.id for s in first.segments.values() if s.outcome == "selected"}
    rejected_before = {s.id for s in first.segments.values() if s.outcome == "rejected"}

    runner.invoke(app, ["select", str(out), "--diversity", "1", "--config", str(toml)])
    second = Manifest.load(out / "manifest.json")
    diverse = {s.id for s in second.segments.values() if s.outcome == "selected"}
    rejected_after = {s.id for s in second.segments.values() if s.outcome == "rejected"}

    assert second.selection.diversity_lambda == 1.0
    # Rejections are not selection's business and must survive both runs untouched.
    assert rejected_before == rejected_after
    assert greedy and diverse


@pytest.mark.ffmpeg
def test_select_never_spawns_ffmpeg(
    synthetic_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selection is a cache read; a decode here would defeat the tuning loop."""
    import subprocess

    out = tmp_path / "edit"
    toml = config_file(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "analyze",
                str(synthetic_dir),
                "--out",
                str(out),
                "--workers",
                "2",
                "--config",
                str(toml),
            ],
        ).exit_code
        == 0
    )

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("select must not start ffmpeg")

    monkeypatch.setattr(subprocess, "Popen", explode)
    result = runner.invoke(app, ["select", str(out), "--config", str(toml)])
    assert result.exit_code == 0, result.stdout


@pytest.mark.ffmpeg
def test_run_chains_analyze_select_and_report(synthetic_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "edit"
    result = runner.invoke(
        app,
        [
            "run",
            str(synthetic_dir),
            "--out",
            str(out),
            "--workers",
            "2",
            "--max-clips",
            "4",
            "--config",
            str(config_file(tmp_path)),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "manifest.json").exists()
    assert (out / "report.html").exists()

    manifest = Manifest.load(out / "manifest.json")
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    assert selected
    assert len(selected) <= 4


def test_export_without_a_manifest_exits_non_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["export", str(tmp_path)])
    assert result.exit_code != 0
    assert "No manifest found" in result.stdout


def test_export_help_lists_the_overrides() -> None:
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    for flag in ("--no-audio", "--fps", "--fast", "--rejects"):
        assert flag in result.stdout


@pytest.mark.ffmpeg
def test_export_without_a_selection_says_to_select_first(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "edit"
    toml = config_file(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "analyze",
                str(synthetic_dir),
                "--out",
                str(out),
                "--workers",
                "2",
                "--config",
                str(toml),
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(app, ["export", str(out), "--config", str(toml)])
    assert result.exit_code == 1
    assert "Nothing selected" in result.stdout


def analyzed_and_selected(
    synthetic_dir: Path, tmp_path: Path, *select_args: str
) -> tuple[Path, Path]:
    """Run analyze then select on the synthetic folder. Returns the project and config."""
    out = tmp_path / "edit"
    toml = config_file(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "analyze",
                str(synthetic_dir),
                "--out",
                str(out),
                "--workers",
                "2",
                "--config",
                str(toml),
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["select", str(out), "--config", str(toml), *select_args]).exit_code == 0
    )
    return out, toml


@pytest.mark.ffmpeg
def test_export_writes_numbered_clips_into_selects(synthetic_dir: Path, tmp_path: Path) -> None:
    out, toml = analyzed_and_selected(synthetic_dir, tmp_path)

    result = runner.invoke(app, ["export", str(out), "--config", str(toml)])
    assert result.exit_code == 0, result.stdout

    manifest = Manifest.load(out / "manifest.json")
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    assert selected
    clips = sorted((out / "_selects").glob("*.mp4"))
    assert len(clips) == len(selected)
    # Alphabetical order is selection order, which is what CapCut imports on.
    assert [clip.name for clip in clips] == sorted(clip.name for clip in clips)
    for index, clip in enumerate(clips, start=1):
        assert clip.name.startswith(f"{index:03d}_")
    for segment in selected:
        assert segment.exported_path is not None
        assert segment.exported_path.exists()
        assert segment.export_mode == "precise"
    assert manifest.export.target_fps == 25.0


@pytest.mark.ffmpeg
def test_a_second_export_skips_everything(synthetic_dir: Path, tmp_path: Path) -> None:
    out, toml = analyzed_and_selected(synthetic_dir, tmp_path)
    assert runner.invoke(app, ["export", str(out), "--config", str(toml)]).exit_code == 0

    result = runner.invoke(app, ["export", str(out), "--config", str(toml)])
    assert result.exit_code == 0, result.stdout
    assert "unchanged, skipped" in result.stdout
    assert "Exported 0 clips" in result.stdout


@pytest.mark.ffmpeg
def test_export_fps_override_is_recorded(synthetic_dir: Path, tmp_path: Path) -> None:
    out, toml = analyzed_and_selected(synthetic_dir, tmp_path)

    result = runner.invoke(app, ["export", str(out), "--fps", "30", "--config", str(toml)])
    assert result.exit_code == 0, result.stdout
    assert Manifest.load(out / "manifest.json").export.target_fps == 30.0


@pytest.mark.ffmpeg
def test_fast_export_stream_copies(synthetic_dir: Path, tmp_path: Path) -> None:
    out, toml = analyzed_and_selected(synthetic_dir, tmp_path)

    result = runner.invoke(app, ["export", str(out), "--fast", "--config", str(toml)])
    assert result.exit_code == 0, result.stdout

    manifest = Manifest.load(out / "manifest.json")
    assert manifest.export.mode == "fast"
    for segment in manifest.segments.values():
        if segment.outcome == "selected":
            assert segment.export_mode == "fast"


@pytest.mark.ffmpeg
def test_export_rejects_lands_in_its_own_folder(synthetic_dir: Path, tmp_path: Path) -> None:
    out, toml = analyzed_and_selected(synthetic_dir, tmp_path)

    result = runner.invoke(app, ["export", str(out), "--rejects", "--config", str(toml)])
    assert result.exit_code == 0, result.stdout

    manifest = Manifest.load(out / "manifest.json")
    rejected = [s for s in manifest.segments.values() if s.outcome == "rejected"]
    assert rejected
    clips = list((out / "_rejects").glob("*.mp4"))
    assert clips
    for clip in clips:
        # The reason takes the place of the tag.
        assert any(segment.reason and segment.reason in clip.name for segment in rejected)


@pytest.mark.ffmpeg
def test_export_refreshes_the_report_with_the_links(synthetic_dir: Path, tmp_path: Path) -> None:
    out, toml = analyzed_and_selected(synthetic_dir, tmp_path)
    assert runner.invoke(app, ["export", str(out), "--config", str(toml)]).exit_code == 0

    html = (out / "report.html").read_text(encoding="utf-8")
    assert "_selects/001_" in html
    assert "Exported" in html

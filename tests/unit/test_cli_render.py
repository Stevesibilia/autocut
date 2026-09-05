"""The render command: the file it writes, the export it runs first, and what it says."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile

pytestmark = pytest.mark.ffmpeg

runner = CliRunner()

CLIPS = ("sharp_pan.mp4", "static.mp4", "multishot.mp4")
CLICK = "click_120bpm.wav"


def project_in(tmp_path: Path, synthetic: Path, selected: bool = True) -> Path:
    """A project the render can work on, with its cache pointed at the temp folder."""
    project = tmp_path / "edit"
    project.mkdir(parents=True)
    (tmp_path / "autocut.toml").write_text(
        f'[cache]\ndir = "{(tmp_path / "cache").as_posix()}"\n', encoding="utf-8"
    )
    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[synthetic], output_dir=project)
    for index, name in enumerate(CLIPS):
        file_id = f"f{index}"
        manifest.files[file_id] = SourceFile(
            id=file_id,
            path=synthetic / name,
            source_class="actioncam",
            duration_s=6.0,
            width=640,
            height=360,
            fps=25.0,
            codec="h264",
            pix_fmt="yuv420p",
        )
        manifest.segments[f"{file_id}:0"] = Segment(
            id=f"{file_id}:0",
            file_id=file_id,
            start_s=0.0,
            end_s=6.0,
            trimmed_start_s=0.0,
            trimmed_end_s=6.0,
            best_center_s=3.0,
            target_duration_s=1.0,
            duration_reason="base",
            outcome="selected" if selected else "candidate",
            order=index + 1 if selected else None,
            score=0.5,
            metrics=Metrics(
                sharpness=100.0,
                exposure_clipped=0.0,
                motion=0.3,
                stability=0.9,
                colorfulness=0.2,
            ),
        )
    manifest.save(project / "manifest.json")
    return project


def config_of(tmp_path: Path) -> list[str]:
    return ["--config", str(tmp_path / "autocut.toml")]


def test_render_needs_a_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["render", str(tmp_path / "nowhere")])

    assert result.exit_code == 1
    assert "No manifest found" in result.stdout


def test_render_needs_a_selection(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir, selected=False)

    result = runner.invoke(app, ["render", str(project), *config_of(tmp_path)])

    assert result.exit_code == 1
    assert "Nothing selected" in result.stdout


def test_a_missing_track_is_refused_before_anything_runs(
    tmp_path: Path, synthetic_dir: Path
) -> None:
    project = project_in(tmp_path, synthetic_dir)

    result = runner.invoke(
        app,
        ["render", str(project), "--track", str(tmp_path / "gone.mp3"), *config_of(tmp_path)],
    )

    assert result.exit_code == 1
    assert "No such track" in result.stdout
    assert not (project / "montage.mp4").exists()


def test_render_exports_first_and_writes_the_file(tmp_path: Path, synthetic_dir: Path) -> None:
    """Nothing has been exported, so the render's own input has to be made first."""
    project = project_in(tmp_path, synthetic_dir)

    result = runner.invoke(app, ["render", str(project), *config_of(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Exported" in result.stdout
    assert "Rendered" in result.stdout
    assert (project / "montage.mp4").exists()
    assert (project / "_selects").is_dir()
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.render.path == project / "montage.mp4"
    assert manifest.render.clips == 3
    assert manifest.render.fingerprint is not None


def test_a_second_run_renders_nothing(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir)
    assert runner.invoke(app, ["render", str(project), *config_of(tmp_path)]).exit_code == 0
    stamp = (project / "montage.mp4").stat().st_mtime_ns

    result = runner.invoke(app, ["render", str(project), *config_of(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Nothing changed since the last render" in result.stdout
    assert (project / "montage.mp4").stat().st_mtime_ns == stamp


def test_a_track_is_muxed_and_named(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir)

    result = runner.invoke(
        app,
        ["render", str(project), "--track", str(synthetic_dir / CLICK), *config_of(tmp_path)],
    )

    assert result.exit_code == 0, result.stdout
    assert CLICK in result.stdout
    assert "1.5 s fade out" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.render.has_audio
    assert manifest.render.track_path == synthetic_dir / CLICK


def test_out_puts_the_file_where_it_is_asked_to(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir)
    elsewhere = tmp_path / "delivery" / "holiday.mp4"

    result = runner.invoke(
        app, ["render", str(project), "--out", str(elsewhere), *config_of(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout
    assert elsewhere.exists()
    assert not (project / "montage.mp4").exists()


def test_the_report_names_the_render(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir)

    result = runner.invoke(app, ["render", str(project), *config_of(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Report written to" in result.stdout
    assert "montage.mp4" in (project / "report.html").read_text(encoding="utf-8")


def test_export_renders_too_when_the_config_asks_for_it(
    tmp_path: Path, synthetic_dir: Path
) -> None:
    """The Export screen's toggle is this setting, so the command line honours it."""
    project = project_in(tmp_path, synthetic_dir)
    (tmp_path / "autocut.toml").write_text(
        f'[cache]\ndir = "{(tmp_path / "cache").as_posix()}"\n\n[render]\nenabled = true\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["export", str(project), *config_of(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (project / "montage.mp4").exists()
    assert "Rendered" in result.stdout


def test_export_alone_renders_nothing(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir)

    result = runner.invoke(app, ["export", str(project), *config_of(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert not (project / "montage.mp4").exists()


def test_the_export_flag_puts_every_clip_on_one_frame(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir)

    result = runner.invoke(app, ["export", str(project), "--uniform-frame", *config_of(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "every clip on one 640x360 frame" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert (manifest.export.frame_width, manifest.export.frame_height) == (640, 360)


def test_a_fast_mode_project_cannot_render(tmp_path: Path, synthetic_dir: Path) -> None:
    project = project_in(tmp_path, synthetic_dir)
    (tmp_path / "autocut.toml").write_text(
        f'[cache]\ndir = "{(tmp_path / "cache").as_posix()}"\n\n[export]\nmode = "fast"\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["render", str(project), *config_of(tmp_path)])

    assert result.exit_code == 1
    assert "precise" in result.stdout
    assert not (project / "_selects").exists()

"""The sync command against the click fixture, including a re-sync at another tempo."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core.beatsync import BEATMAP_FILENAME
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile

pytestmark = pytest.mark.ffmpeg

runner = CliRunner()

CLICK = "click_120bpm.wav"


def project_in(
    tmp_path: Path, clips: int = 6, selected: bool = True, proposed: float | None = 120.0
) -> Path:
    project = tmp_path / "edit"
    project.mkdir(parents=True)
    (tmp_path / "autocut.toml").write_text(
        f'[cache]\ndir = "{(tmp_path / "cache").as_posix()}"\n', encoding="utf-8"
    )
    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=project)
    for index in range(clips):
        file_id = f"f{index}"
        manifest.files[file_id] = SourceFile(
            id=file_id,
            path=Path(f"/f/{file_id}.MP4"),
            source_class="actioncam",
            duration_s=60.0,
            width=1920,
            height=1080,
            fps=25.0,
            codec="h264",
            pix_fmt="yuv420p",
        )
        manifest.segments[f"{file_id}:0"] = Segment(
            id=f"{file_id}:0",
            file_id=file_id,
            start_s=0.0,
            end_s=20.0,
            trimmed_start_s=0.0,
            trimmed_end_s=20.0,
            best_center_s=10.0,
            # A spread of assigned lengths, so the rounding has something to do.
            target_duration_s=2.2 if index % 2 else 4.1,
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
    manifest.soundtrack.proposed_bpm = proposed
    manifest.save(project / "manifest.json")
    return project


def test_sync_measures_the_track_and_rounds_the_clips(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK)])

    assert result.exit_code == 0, result.stdout
    assert "Measured 120 bpm" in result.stdout
    assert "beats per clip" in result.stdout

    manifest = Manifest.load(project / "manifest.json")
    assert manifest.soundtrack.measured_bpm == pytest.approx(120.0, abs=1.0)
    assert manifest.soundtrack.comparison == "agreed"
    assert manifest.soundtrack.beats_s
    assert manifest.soundtrack.audio_path is not None
    for segment in manifest.segments.values():
        assert segment.beats in (4, 8)
        assert segment.duration_reason == "beat"
        assert segment.final_start_s is not None
        assert segment.final_end_s is not None


def test_the_beat_map_is_written(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK)])

    assert result.exit_code == 0, result.stdout
    path = project / BEATMAP_FILENAME
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "bpm" in text
    assert "# order  start  beats  name" in text
    assert "edit length" in text
    assert Manifest.load(project / "manifest.json").soundtrack.beatmap_path is not None


def test_the_bpm_override_is_used_and_recorded(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario from the spec: 124 is used and both numbers are kept."""
    project = project_in(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK), "--bpm", "124"]
    )

    assert result.exit_code == 0, result.stdout
    assert "using 124 as asked" in result.stdout

    manifest = Manifest.load(project / "manifest.json")
    assert manifest.soundtrack.bpm_override == 124
    assert manifest.soundtrack.measured_bpm == pytest.approx(120.0, abs=1.0)
    segment = next(iter(manifest.segments.values()))
    assert segment.beats is not None
    assert segment.target_duration_s == pytest.approx(segment.beats * 60 / 124)


def test_a_re_sync_at_another_tempo_replaces_the_bounds(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario from the spec: sync at 110 then at 124 reflects 124."""
    project = project_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    audio = str(synthetic_dir / CLICK)

    runner.invoke(app, ["sync", str(project), "--audio", audio, "--bpm", "110"])
    first = Manifest.load(project / "manifest.json")
    at_110 = {key: segment.final_end_s for key, segment in first.segments.items()}

    runner.invoke(app, ["sync", str(project), "--audio", audio, "--bpm", "124"])
    second = Manifest.load(project / "manifest.json")

    assert second.soundtrack.bpm_override == 124
    for key, segment in second.segments.items():
        assert segment.beats is not None
        # The length is beats of the new tempo, and the bounds moved with it.
        assert segment.target_duration_s == pytest.approx(segment.beats * 60 / 124)
        assert segment.final_end_s != pytest.approx(at_110[key])


def test_a_re_sync_does_not_compound_the_rounding(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Syncing twice at one tempo has to be the same as syncing once."""
    project = project_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    audio = str(synthetic_dir / CLICK)

    runner.invoke(app, ["sync", str(project), "--audio", audio, "--bpm", "120"])
    once = {
        key: (segment.beats, segment.target_duration_s)
        for key, segment in Manifest.load(project / "manifest.json").segments.items()
    }

    runner.invoke(app, ["sync", str(project), "--audio", audio, "--bpm", "120"])
    twice = {
        key: (segment.beats, segment.target_duration_s)
        for key, segment in Manifest.load(project / "manifest.json").segments.items()
    }

    assert once == twice


def test_the_comparison_warns_when_the_track_drifted(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, proposed=100.0)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK)])

    assert result.exit_code == 0, result.stdout
    assert "against a proposed 100" in result.stdout
    assert Manifest.load(project / "manifest.json").soundtrack.comparison == "drifted"


def test_the_comparison_spots_half_tempo(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proposal of 240 against a 120 track is the tracker's usual halving."""
    project = project_in(tmp_path, proposed=240.0)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK)])

    assert "half" in result.stdout
    assert "--bpm 240" in result.stdout
    assert Manifest.load(project / "manifest.json").soundtrack.comparison == "half"


def test_sync_works_without_a_proposed_bpm(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The soundtrack step is optional, so sync says the comparison was skipped."""
    project = project_in(tmp_path, proposed=None)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK)])

    assert result.exit_code == 0, result.stdout
    assert "nothing to compare" in result.stdout
    assert Manifest.load(project / "manifest.json").soundtrack.comparison == "no proposal"


def test_a_project_with_nothing_selected_exits_non_zero(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, selected=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK)])

    assert result.exit_code == 1
    assert "Nothing selected" in result.stdout


def test_a_missing_track_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(tmp_path / "nope.wav")])

    assert result.exit_code == 1
    assert "No such track" in result.stdout


def test_a_track_that_will_not_decode_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not a wav")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(broken)])

    assert result.exit_code == 1
    assert "could not decode" in result.stdout


def test_the_summary_says_how_the_edit_length_changed(
    tmp_path: Path, synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["sync", str(project), "--audio", str(synthetic_dir / CLICK)])

    assert "Quantized 6 clips" in result.stdout
    assert "mean move" in result.stdout

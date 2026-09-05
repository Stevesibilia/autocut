"""The finished file: joined from the export, muxed with the track, and not rebuilt."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressEvent
from autocut.core.export import export_clips
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile
from autocut.core.render import (
    check_parts_uniform,
    exported_clips,
    is_current,
    render_edit,
    render_fingerprint,
    render_path,
    resolve_track,
)

pytestmark = pytest.mark.ffmpeg

CLIPS = ("sharp_pan.mp4", "static.mp4", "multishot.mp4")


def settings(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    # One process, so a three clip export in a test is not a pool of spawned children.
    config.analysis.workers = 2
    return config


def project(
    tmp_path: Path, synthetic: Path, clips: tuple[str, ...] = CLIPS, source: str = "actioncam"
) -> Manifest:
    """A selected project over the synthetic clips, ready to export."""
    now = datetime.now(UTC)
    out = tmp_path / "edit"
    out.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(created_at=now, updated_at=now, sources=[synthetic], output_dir=out)
    for index, name in enumerate(clips):
        file_id = f"f{index}"
        manifest.files[file_id] = SourceFile(
            id=file_id,
            path=synthetic / name,
            source_class=source,
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
            outcome="selected",
            order=index + 1,
            score=0.5,
            metrics=Metrics(
                sharpness=100.0,
                exposure_clipped=0.0,
                motion=0.3,
                stability=0.9,
                colorfulness=0.2,
            ),
        )
    return manifest


@pytest.fixture
def exported(tmp_path: Path, synthetic_dir: Path) -> tuple[Manifest, AutocutConfig]:
    """A project whose clips are already in ``_selects/``, which is the render's input."""
    config = settings(tmp_path)
    manifest = project(tmp_path, synthetic_dir)
    result = export_clips(manifest, config)
    assert result.failed == 0, result.errors
    return manifest, config


def streams(path: Path, kind: str) -> list[dict[str, object]]:
    """The streams of one kind in a file, straight from ffprobe."""
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            kind,
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(completed.stdout or "{}")
    streams_found = payload.get("streams", [])
    assert isinstance(streams_found, list)
    return streams_found


def duration(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return float(completed.stdout.strip())


def tail_volume(path: Path, seconds: float) -> float:
    """Mean volume of the last ``seconds`` of a file, in dBFS.

    The only honest way to test a fade is to listen to the end of the file.
    """
    total = duration(path)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-nostdin",
            "-ss",
            f"{max(0.0, total - seconds):.3f}",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in completed.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].strip().split(" ")[0])
    raise AssertionError(f"volumedetect said nothing about {path.name}")


# --- what it writes -----------------------------------------------------------


def test_the_render_is_as_long_as_its_clips_together(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """The whole promise of a stream copy concat: nothing is dropped and nothing added."""
    manifest, config = exported
    paths, missing = exported_clips(manifest)
    assert not missing
    expected = sum(duration(path) for path in paths)

    result = render_edit(manifest, config)

    assert result.ok, result.errors
    assert result.path is not None
    assert abs(duration(result.path) - expected) <= 1 / 25.0
    assert len(streams(result.path, "v")) == 1


def test_the_render_lands_beside_the_selects_folder(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """Inside ``_selects/`` it would be imported into CapCut as a twenty-ninth clip."""
    manifest, config = exported

    result = render_edit(manifest, config)

    assert result.path == Path(manifest.output_dir) / "montage.mp4"
    assert result.path == render_path(manifest, config)


def test_a_track_becomes_the_audio(
    exported: tuple[Manifest, AutocutConfig], synthetic_dir: Path
) -> None:
    manifest, config = exported
    track = synthetic_dir / "click_120bpm.wav"

    result = render_edit(manifest, config, track=track)

    assert result.ok, result.errors
    assert result.path is not None
    assert result.has_audio
    audio = streams(result.path, "a")
    assert len(audio) == 1
    assert audio[0]["codec_name"] == "aac"
    # The video's length wins: the click track is longer than a three second edit.
    assert abs(duration(result.path) - result.duration_s) < 0.1


def test_without_a_track_silent_clips_render_silent(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, config = exported

    result = render_edit(manifest, config)

    assert result.ok, result.errors
    assert result.path is not None
    assert streams(result.path, "a") == []
    assert not result.has_audio


def test_clip_audio_is_carried_when_the_clips_kept_it(tmp_path: Path, synthetic_dir: Path) -> None:
    """A class whose audio is kept has ambience, and no track was asked for."""
    config = settings(tmp_path)
    config.export.remove_audio.phone = False
    manifest = project(tmp_path, synthetic_dir, clips=("with_audio.mp4",), source="phone")
    assert export_clips(manifest, config).failed == 0

    result = render_edit(manifest, config)

    assert result.ok, result.errors
    assert result.path is not None
    assert result.has_audio
    assert len(streams(result.path, "a")) == 1


def test_the_fade_is_audible_at_the_end(
    exported: tuple[Manifest, AutocutConfig], synthetic_dir: Path
) -> None:
    """Measured rather than asserted on the command: a filter that never ran is not a fade."""
    manifest, config = exported
    track = synthetic_dir / "click_120bpm.wav"
    config.render.fade_out_seconds = 0.0
    flat = render_edit(manifest, config, track=track, out=manifest.output_dir / "flat.mp4")
    assert flat.ok, flat.errors
    assert flat.path is not None

    config.render.fade_out_seconds = 1.0
    faded = render_edit(manifest, config, track=track, out=manifest.output_dir / "faded.mp4")

    assert faded.ok, faded.errors
    assert faded.path is not None
    assert tail_volume(faded.path, 0.5) < tail_volume(flat.path, 0.5) - 3.0


# --- when it does not write ---------------------------------------------------


def test_a_second_render_writes_nothing(exported: tuple[Manifest, AutocutConfig]) -> None:
    manifest, config = exported
    first = render_edit(manifest, config)
    assert first.path is not None
    stamp = first.path.stat().st_mtime_ns

    again = render_edit(manifest, config)

    assert again.reused
    assert again.path == first.path
    assert again.path is not None and again.path.stat().st_mtime_ns == stamp
    assert again.fingerprint == first.fingerprint


def test_force_renders_over_an_unchanged_edit(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, config = exported
    first = render_edit(manifest, config)
    assert first.path is not None
    stamp = first.path.stat().st_mtime_ns

    again = render_edit(manifest, config, force=True)

    assert not again.reused
    assert again.path is not None and again.path.stat().st_mtime_ns != stamp


def test_a_new_track_makes_the_render_stale(
    exported: tuple[Manifest, AutocutConfig], synthetic_dir: Path
) -> None:
    manifest, config = exported
    render_edit(manifest, config)
    track = synthetic_dir / "click_120bpm.wav"

    assert not is_current(manifest, config, track)

    result = render_edit(manifest, config, track=track)

    assert not result.reused
    assert result.has_audio


def test_a_longer_fade_makes_the_render_stale(
    exported: tuple[Manifest, AutocutConfig], synthetic_dir: Path
) -> None:
    """The fade is in the file, so it has to be in the fingerprint."""
    manifest, config = exported
    track = synthetic_dir / "click_120bpm.wav"
    before = render_fingerprint(manifest, config, track)

    config.render.fade_out_seconds = 4.0

    assert render_fingerprint(manifest, config, track) != before


# --- the export it depends on -------------------------------------------------


def test_a_stale_export_is_run_first(exported: tuple[Manifest, AutocutConfig]) -> None:
    """A render over yesterday's clips would show an edit that no longer exists."""
    manifest, config = exported
    render_edit(manifest, config)
    manifest.segments["f1:0"].outcome = "rejected"
    manifest.segments["f1:0"].order = None
    manifest.segments["f2:0"].order = 2

    result = render_edit(manifest, config)

    assert result.ok, result.errors
    assert result.export is not None
    assert result.clips == 2
    assert result.path is not None
    paths, _missing = exported_clips(manifest)
    assert abs(duration(result.path) - sum(duration(path) for path in paths)) <= 1 / 25.0


def test_nothing_selected_renders_nothing(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, synthetic_dir)
    for segment in manifest.segments.values():
        segment.outcome = "candidate"

    result = render_edit(manifest, config)

    assert result.path is None
    assert result.skipped_reason == "nothing is selected"


def test_progress_reports_the_render_stage(exported: tuple[Manifest, AutocutConfig]) -> None:
    manifest, config = exported
    seen: list[ProgressEvent] = []

    render_edit(manifest, config, progress=seen.append)

    assert [event.stage for event in seen if event.stage == "render"]
    assert seen[-1].current == seen[-1].total


# --- clips that cannot be joined ----------------------------------------------


def test_clips_of_different_sizes_are_refused(
    exported: tuple[Manifest, AutocutConfig], tmp_path: Path
) -> None:
    """A fast mode export stream copies its sources, so a folder can hold both."""
    manifest, config = exported
    paths, _missing = exported_clips(manifest)
    odd = paths[1]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(odd),
            "-vf",
            "scale=320:-2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(tmp_path / "small.mp4"),
        ],
        check=True,
    )
    (tmp_path / "small.mp4").replace(odd)

    check = check_parts_uniform(paths)
    result = render_edit(manifest, config)

    assert not check.uniform
    assert check.error is not None and "re-encoding" in check.error
    assert not result.ok
    assert result.errors and "re-encoding" in result.errors[0][1]
    assert not render_path(manifest, config).exists()


def test_a_missing_clip_is_reported(exported: tuple[Manifest, AutocutConfig]) -> None:
    manifest, config = exported
    paths, _missing = exported_clips(manifest)
    paths[0].unlink()

    check = check_parts_uniform(paths)

    assert not check.uniform
    assert check.error is not None and "missing" in check.error


# --- which track ---------------------------------------------------------------


def test_the_synced_track_is_preferred_over_a_newly_loaded_one(
    exported: tuple[Manifest, AutocutConfig], synthetic_dir: Path, tmp_path: Path
) -> None:
    """The clips were cut to the synced track; another one would be a silent mismatch."""
    manifest, _config = exported
    synced = synthetic_dir / "click_120bpm.wav"
    loaded = tmp_path / "loaded.wav"
    loaded.write_bytes(synced.read_bytes())
    manifest.soundtrack.audio_path = loaded
    manifest.soundtrack.synced_audio_path = synced

    assert resolve_track(manifest) == synced
    assert resolve_track(manifest, loaded) == loaded


def test_a_track_that_is_gone_is_not_used(exported: tuple[Manifest, AutocutConfig]) -> None:
    manifest, _config = exported
    manifest.soundtrack.synced_audio_path = Path("/nowhere/gone.mp3")

    assert resolve_track(manifest) is None

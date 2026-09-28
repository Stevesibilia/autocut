"""Export orchestration: fingerprints, skipping, stale files, rejects and failures.

The tests that assert on encoded output carry the ``ffmpeg`` marker and run over the
synthetic fixtures. The rest replace the encoder with a stub, because whether a clip
is skipped has nothing to do with libx264.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressEvent
from autocut.core.export import (
    ClipResult,
    ExportResult,
    export_clips,
    export_one,
    fingerprint,
)
from autocut.core.ffmpeg_cmd import ExportOverrides, plan_export
from autocut.core.manifest import Manifest, Segment, SourceFile
from autocut.core.naming import REJECTS_DIR, SELECTS_DIR, STALE_DIR

DAY = datetime(2026, 8, 12, 10, 30, tzinfo=UTC)


def project(tmp_path: Path) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(
        created_at=now, updated_at=now, sources=[Path("/f")], output_dir=tmp_path / "edit"
    )


def add_file(
    manifest: Manifest,
    file_id: str,
    source_class: str = "drone",
    path: Path | None = None,
    fps: float = 25.0,
    minutes: float = 0.0,
) -> SourceFile:
    from datetime import timedelta

    source = SourceFile(
        id=file_id,
        path=path or Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=6.0,
        width=640,
        height=360,
        fps=fps,
        codec="h264",
        pix_fmt="yuv420p",
        creation_time=DAY + timedelta(minutes=minutes),
    )
    manifest.files[file_id] = source
    return source


def add_segment(
    manifest: Manifest,
    segment_id: str,
    file_id: str,
    outcome: str = "selected",
    order: int | None = 1,
    reason: str | None = None,
    center: float = 3.0,
    duration: float = 2.0,
) -> Segment:
    segment = Segment(
        id=segment_id,
        file_id=file_id,
        start_s=0.0,
        end_s=6.0,
        trimmed_start_s=0.0,
        trimmed_end_s=6.0,
        best_center_s=center,
        target_duration_s=duration,
        outcome=outcome,  # type: ignore[arg-type]
        order=order,
        reason=reason,
    )
    manifest.segments[segment_id] = segment
    return segment


def stub_encoder(monkeypatch: pytest.MonkeyPatch, fail: set[str] | None = None) -> list[Path]:
    """Replace ffmpeg with a stub that writes an empty file. Returns what it wrote."""
    written: list[Path] = []
    failing = fail or set()

    def fake(plan: object, segment_id: str, digest: str) -> ClipResult:
        assert hasattr(plan, "output")
        output: Path = plan.output  # type: ignore[attr-defined]
        if segment_id in failing:
            return ClipResult(segment_id, output, digest, error="stub failure")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"clip")
        written.append(output)
        return ClipResult(segment_id, output, digest)

    monkeypatch.setattr("autocut.core.export.export_one", fake)
    return written


def one_worker(config: AutocutConfig) -> AutocutConfig:
    """Keep the pool out of the way: a stub encoder cannot cross a process boundary."""
    config.analysis.workers = 1
    return config


# --- fingerprints ------------------------------------------------------------


def fingerprint_of(tmp_path: Path, config: AutocutConfig | None = None, **kwargs: object) -> str:
    manifest = project(tmp_path)
    source = add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a", **kwargs)  # type: ignore[arg-type]
    plan = plan_export(segment, source, manifest, config or AutocutConfig())
    return fingerprint(plan, source.id)


def test_the_same_settings_give_the_same_fingerprint(tmp_path: Path) -> None:
    assert fingerprint_of(tmp_path) == fingerprint_of(tmp_path)


def test_a_moved_window_changes_the_fingerprint(tmp_path: Path) -> None:
    assert fingerprint_of(tmp_path, center=3.0) != fingerprint_of(tmp_path, center=4.0)


def test_a_changed_setting_changes_the_fingerprint(tmp_path: Path) -> None:
    louder = AutocutConfig()
    louder.export.crf = 20
    assert fingerprint_of(tmp_path) != fingerprint_of(tmp_path, louder)


def test_a_changed_maximum_changes_the_fingerprint(tmp_path: Path) -> None:
    smaller = AutocutConfig()
    smaller.export.max_width, smaller.export.max_height = 320, 180
    assert fingerprint_of(tmp_path) != fingerprint_of(tmp_path, smaller)


# --- orchestration -----------------------------------------------------------


def test_every_selected_clip_gets_an_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    for index in range(3):
        add_file(manifest, f"f{index}", minutes=index * 10)
        add_segment(manifest, f"f{index}:0", f"f{index}", order=index + 1)

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 3
    assert len(written) == 3
    for segment in manifest.segments.values():
        assert segment.exported_path is not None
        assert segment.exported_path.parent.name == SELECTS_DIR
        assert segment.export_fingerprint is not None
        assert segment.export_error is None


def test_names_carry_the_selection_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    for index in range(3):
        add_file(manifest, f"f{index}", minutes=index * 10)
        # Deliberately out of insertion order: the name follows order, not iteration.
        add_segment(manifest, f"f{index}:0", f"f{index}", order=3 - index)

    export_clips(manifest, one_worker(AutocutConfig()))

    by_order = {
        s.order: s.exported_path.name for s in manifest.segments.values() if s.exported_path
    }
    assert by_order[1].startswith("001_")
    assert by_order[2].startswith("002_")
    assert by_order[3].startswith("003_")


def test_a_second_run_skips_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scenario in specs/clip-export: nothing changed, so nothing is encoded."""
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a")
    config = one_worker(AutocutConfig())

    first = export_clips(manifest, config)
    second = export_clips(manifest, config)

    assert first.exported == 1 and first.skipped == 0
    assert second.exported == 0 and second.skipped == 1


def test_a_changed_setting_re_encodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a")
    config = one_worker(AutocutConfig())
    export_clips(manifest, config)

    config.export.crf = 22
    again = export_clips(manifest, config)

    assert again.exported == 1 and again.skipped == 0


def test_a_deleted_output_is_encoded_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a")
    config = one_worker(AutocutConfig())
    export_clips(manifest, config)

    assert segment.exported_path is not None
    segment.exported_path.unlink()
    again = export_clips(manifest, config)

    assert again.exported == 1


def test_a_clip_that_moved_up_the_edit_is_encoded_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two clips of the same day, class, tag and length differ only by their index.

    So when the first one is rejected, the second inherits its name, and a skip decided
    on the fingerprint alone would leave the rejected clip's footage in the folder under
    the name of the clip that is still in the edit.
    """
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    for index in range(2):
        add_file(manifest, f"f{index}")
        add_segment(manifest, f"f{index}:0", f"f{index}", order=index + 1)
    config = one_worker(AutocutConfig())
    export_clips(manifest, config)
    first, second = manifest.segments["f0:0"], manifest.segments["f1:0"]
    assert first.exported_path is not None and second.exported_path is not None
    assert first.exported_path.name.startswith("001_")
    assert second.exported_path.name.startswith("002_")

    first.outcome = "rejected"
    first.order = None
    second.order = 1
    again = export_clips(manifest, config)

    assert again.exported == 1 and again.skipped == 0
    assert second.exported_path is not None
    assert second.exported_path.name.startswith("001_")


def test_the_frame_re_encodes_only_the_clips_whose_size_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turning the frame on is one re-encode of the big clips, not of the whole edit."""
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "big", path=Path("/f/big.MP4"))
    manifest.files["big"].width, manifest.files["big"].height = 3840, 2160
    add_file(manifest, "small", source_class="phone", minutes=10)
    manifest.files["small"].width, manifest.files["small"].height = 1920, 1080
    add_segment(manifest, "big:0", "big", order=1)
    add_segment(manifest, "small:0", "small", order=2)
    config = one_worker(AutocutConfig())
    export_clips(manifest, config)

    config.export.uniform_frame = True
    again = export_clips(manifest, config)

    assert again.exported == 1
    assert again.skipped == 1
    assert again.frame == (1920, 1080)
    assert (manifest.export.frame_width, manifest.export.frame_height) == (1920, 1080)


def test_the_recorded_frame_survives_an_export_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise one plain export would let the frame grow on the next render."""
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a")
    config = one_worker(AutocutConfig())
    config.export.uniform_frame = True
    export_clips(manifest, config)
    recorded = manifest.export.frame_width, manifest.export.frame_height
    assert recorded[0]

    config.export.uniform_frame = False
    export_clips(manifest, config)

    assert (manifest.export.frame_width, manifest.export.frame_height) == recorded


def test_the_frame_is_part_of_the_fingerprint_only_when_it_pads(tmp_path: Path) -> None:
    """A project exported before the frame existed must keep its files."""
    manifest = project(tmp_path)
    source = add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a")
    plain = fingerprint(plan_export(segment, source, manifest, AutocutConfig()), source.id)

    config = AutocutConfig()
    config.export.uniform_frame = True
    with_frame = fingerprint(plan_export(segment, source, manifest, config), source.id)

    # The only clip in the edit already is the frame, so nothing about it changes.
    assert with_frame == plain


def test_a_dropped_clip_leaves_its_output_in_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reselect scenario in specs/output-naming."""
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a", minutes=0)
    add_file(manifest, "b", minutes=10)
    kept = add_segment(manifest, "a:0", "a", order=1)
    dropped = add_segment(manifest, "b:0", "b", order=2)
    config = one_worker(AutocutConfig())
    export_clips(manifest, config)
    gone = dropped.exported_path
    assert gone is not None and gone.exists()

    # select drops it and export runs again.
    dropped.outcome = "candidate"
    dropped.order = None
    dropped.exported_path = None
    dropped.export_fingerprint = None
    result = export_clips(manifest, config)

    assert result.stale_moved == 1
    assert not gone.exists()
    assert (gone.parent / STALE_DIR / gone.name).exists()
    assert kept.exported_path is not None and kept.exported_path.exists()


def test_a_failing_clip_does_not_stop_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one-bad-file scenario in specs/clip-export."""
    stub_encoder(monkeypatch, fail={"b:0"})
    manifest = project(tmp_path)
    add_file(manifest, "a", minutes=0)
    add_file(manifest, "b", minutes=10)
    add_segment(manifest, "a:0", "a", order=1)
    add_segment(manifest, "b:0", "b", order=2)

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 1
    assert result.failed == 1
    assert result.errors == [("b:0", "stub failure")]
    assert manifest.segments["a:0"].exported_path is not None
    assert manifest.segments["b:0"].exported_path is None
    assert manifest.segments["b:0"].export_error == "stub failure"


def test_a_failure_is_retried_on_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clip with no output and no fingerprint cannot be mistaken for done."""
    stub_encoder(monkeypatch, fail={"a:0"})
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a")
    config = one_worker(AutocutConfig())
    assert export_clips(manifest, config).failed == 1

    stub_encoder(monkeypatch)
    assert export_clips(manifest, config).exported == 1


def test_rejects_are_exported_with_the_reason_in_the_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a", minutes=0)
    add_file(manifest, "b", minutes=10)
    add_segment(manifest, "a:0", "a", order=1)
    bad = add_segment(manifest, "b:0", "b", outcome="rejected", order=None, reason="low_altitude")

    export_clips(manifest, one_worker(AutocutConfig()), overrides=ExportOverrides(rejects=True))

    assert bad.exported_path is not None
    assert bad.exported_path.parent.name == REJECTS_DIR
    assert "low_altitude" in bad.exported_path.name


def test_rejects_stay_out_of_the_way_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", order=1)
    add_file(manifest, "b", minutes=10)
    bad = add_segment(manifest, "b:0", "b", outcome="rejected", order=None, reason="shaky")

    export_clips(manifest, one_worker(AutocutConfig()))

    assert bad.exported_path is None
    assert not (Path(manifest.output_dir) / REJECTS_DIR).exists()


def test_the_config_can_ask_for_rejects_without_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", order=1)
    add_file(manifest, "b", minutes=10)
    bad = add_segment(manifest, "b:0", "b", outcome="rejected", order=None, reason="shaky")
    config = one_worker(AutocutConfig())
    config.export.keep_rejects = True

    export_clips(manifest, config)

    assert bad.exported_path is not None


def test_a_reject_export_does_not_make_a_select_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only _selects is swept, so a rejects folder cannot displace the edit."""
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    kept = add_segment(manifest, "a:0", "a", order=1)
    add_file(manifest, "b", minutes=10)
    add_segment(manifest, "b:0", "b", outcome="rejected", order=None, reason="shaky")
    config = one_worker(AutocutConfig())

    export_clips(manifest, config)
    result = export_clips(manifest, config, overrides=ExportOverrides(rejects=True))

    assert result.stale_moved == 0
    assert kept.exported_path is not None and kept.exported_path.exists()


def test_progress_reports_every_clip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    for index in range(3):
        add_file(manifest, f"f{index}", minutes=index * 10)
        add_segment(manifest, f"f{index}:0", f"f{index}", order=index + 1)
    events: list[ProgressEvent] = []

    export_clips(manifest, one_worker(AutocutConfig()), events.append)

    assert [event.stage for event in events] == ["export"] * 3
    assert events[-1].current == events[-1].total == 3


def test_the_run_is_recorded_on_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a")

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert manifest.export.ran_at is not None
    assert manifest.export.target_fps == result.target_fps == 25.0
    assert manifest.export.mode == "precise"
    assert manifest.export.codec == "libx264"
    assert manifest.export.exported == 1


def test_fast_mode_is_recorded_on_every_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a")

    export_clips(manifest, one_worker(AutocutConfig()), overrides=ExportOverrides(fast=True))

    assert segment.export_mode == "fast"
    assert manifest.export.mode == "fast"


def test_a_resampled_clip_is_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a", fps=25.0, minutes=0)
    add_file(manifest, "b", fps=30.0, minutes=10)
    add_file(manifest, "c", fps=50.0, minutes=20)
    plain = add_segment(manifest, "a:0", "a", order=1)
    odd = add_segment(manifest, "b:0", "b", order=2)
    doubled = add_segment(manifest, "c:0", "c", order=3)

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.target_fps == 25.0
    assert plain.fps_converted is False
    assert odd.fps_converted is True
    assert doubled.fps_converted is False
    assert result.fps_converted == 1


def test_an_empty_selection_exports_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_file(manifest, "a")
    add_segment(manifest, "a:0", "a", outcome="candidate", order=None)

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.total == 0
    assert isinstance(result, ExportResult)


def test_a_segment_whose_file_is_gone_is_reported_not_crashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoder(monkeypatch)
    manifest = project(tmp_path)
    add_segment(manifest, "ghost:0", "ghost")

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.total == 0
    assert any("ghost:0" in warning for warning in result.warnings)


# --- the encoder itself ------------------------------------------------------


@pytest.mark.ffmpeg
def test_a_real_clip_lands_at_the_exact_duration(synthetic_dir: Path, tmp_path: Path) -> None:
    """The exact duration scenario in specs/clip-export, within one frame at 25 fps."""
    manifest = project(tmp_path)
    add_file(manifest, "a", path=synthetic_dir / "sharp_pan.mp4")
    segment = add_segment(manifest, "a:0", "a", center=3.0, duration=3.0)

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 1, result.errors
    assert segment.exported_path is not None and segment.exported_path.exists()
    # One frame at the target rate, which is what the requirement is about. The source
    # rate happens to be the same here, and would be the wrong tolerance elsewhere.
    assert abs(probe_duration(segment.exported_path) - 3.0) <= 1 / result.target_fps


@pytest.mark.ffmpeg
def test_every_class_is_silent_by_default(synthetic_dir: Path, tmp_path: Path) -> None:
    """The silent by default scenario in specs/clip-export, on a clip that has audio."""
    manifest = project(tmp_path)
    add_file(manifest, "d", "drone", path=synthetic_dir / "with_audio.mp4", minutes=0)
    add_file(manifest, "p", "phone", path=synthetic_dir / "with_audio.mp4", minutes=10)
    drone = add_segment(manifest, "d:0", "d", order=1)
    phone = add_segment(manifest, "p:0", "p", order=2)

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 2, result.errors
    assert drone.exported_path is not None and phone.exported_path is not None
    assert "audio" not in probe_streams(drone.exported_path)
    assert "audio" not in probe_streams(phone.exported_path)


@pytest.mark.ffmpeg
def test_a_class_can_opt_back_into_its_ambience(synthetic_dir: Path, tmp_path: Path) -> None:
    """The drone silent, phone keeps ambience scenario in specs/clip-export."""
    manifest = project(tmp_path)
    add_file(manifest, "d", "drone", path=synthetic_dir / "with_audio.mp4", minutes=0)
    add_file(manifest, "p", "phone", path=synthetic_dir / "with_audio.mp4", minutes=10)
    drone = add_segment(manifest, "d:0", "d", order=1)
    phone = add_segment(manifest, "p:0", "p", order=2)
    config = one_worker(AutocutConfig())
    config.export.remove_audio.phone = False

    result = export_clips(manifest, config)

    assert result.exported == 2, result.errors
    assert drone.exported_path is not None and phone.exported_path is not None
    assert "audio" not in probe_streams(drone.exported_path)
    assert "audio" in probe_streams(phone.exported_path)


@pytest.mark.ffmpeg
def test_no_audio_silences_every_clip(synthetic_dir: Path, tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_file(manifest, "p", "phone", path=synthetic_dir / "with_audio.mp4")
    phone = add_segment(manifest, "p:0", "p")
    config = one_worker(AutocutConfig())
    # The flag has to beat a class that opted back in, not just agree with the default.
    config.export.remove_audio.phone = False

    export_clips(manifest, config, overrides=ExportOverrides(no_audio=True))

    assert phone.exported_path is not None
    assert "audio" not in probe_streams(phone.exported_path)


@pytest.mark.ffmpeg
def test_a_10_bit_source_comes_out_8_bit(synthetic_dir: Path, tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_file(manifest, "a", path=synthetic_dir / "hevc_10bit.mp4")
    segment = add_segment(manifest, "a:0", "a")

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 1, result.errors
    assert segment.exported_path is not None
    assert probe_video(segment.exported_path)["pix_fmt"] == "yuv420p"


@pytest.mark.ffmpeg
def test_slow_motion_stretches_the_source_window(synthetic_dir: Path, tmp_path: Path) -> None:
    """The 50 fps action cam scenario: 1.5 s of source becomes 3.0 s of output."""
    manifest = project(tmp_path)
    add_file(manifest, "c", "actioncam", path=synthetic_dir / "fifty_fps.mp4", fps=50.0)
    segment = add_segment(manifest, "c:0", "c", center=3.0, duration=3.0)
    manifest.export.target_fps = 25.0

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 1, result.errors
    assert result.slow_motion == 1
    assert segment.exported_path is not None
    assert abs(probe_duration(segment.exported_path) - 3.0) <= 1 / result.target_fps
    assert probe_video(segment.exported_path)["r_frame_rate"] == "25/1"


@pytest.mark.ffmpeg
def test_a_rotated_phone_clip_comes_out_upright_without_rotation_metadata(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    """Rotation side data is applied at decode, so no editor has to guess."""
    from autocut.core.probe import probe_file

    probe = probe_file(synthetic_dir / "vertical_rot90.mp4")
    manifest = project(tmp_path)
    source = add_file(manifest, "v", "phone", path=synthetic_dir / "vertical_rot90.mp4")
    source.width, source.height, source.rotation = probe.width, probe.height, probe.rotation
    assert source.is_vertical
    segment = add_segment(manifest, "v:0", "v")
    config = one_worker(AutocutConfig())
    config.export.vertical_strategy = "center_crop"

    result = export_clips(manifest, config)

    assert result.exported == 1, result.errors
    assert segment.exported_path is not None
    stream = probe_video(segment.exported_path)
    assert int(stream["width"]) > int(stream["height"])
    assert probe_rotation(segment.exported_path) == 0


@pytest.mark.ffmpeg
def test_the_telemetry_track_is_not_muxed_into_the_clip(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    """A DJI clip carries its telemetry as a subtitle stream; CapCut has no use for it."""
    manifest = project(tmp_path)
    add_file(manifest, "a", path=synthetic_dir / "drone_embedded_srt.mp4")
    segment = add_segment(manifest, "a:0", "a")

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 1, result.errors
    assert segment.exported_path is not None
    # No telemetry subtitle track, and no timecode track from the muxer either.
    assert probe_streams(segment.exported_path) == ["video"]


@pytest.mark.ffmpeg
def test_an_unreadable_source_records_the_ffmpeg_error(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_file(manifest, "a", path=tmp_path / "not-a-video.mp4")
    segment = add_segment(manifest, "a:0", "a")

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.failed == 1
    assert segment.export_error
    assert segment.exported_path is None


@pytest.mark.ffmpeg
def test_a_failed_clip_leaves_no_partial_file(tmp_path: Path) -> None:
    """A half written file would be taken for a finished output by the next run."""
    manifest = project(tmp_path)
    add_file(manifest, "a", path=tmp_path / "not-a-video.mp4")
    add_segment(manifest, "a:0", "a")

    export_clips(manifest, one_worker(AutocutConfig()))

    selects = Path(manifest.output_dir) / SELECTS_DIR
    assert not selects.exists() or list(selects.glob("*.mp4")) == []


def test_a_worker_exception_does_not_stop_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def flaky(plan: object, segment_id: str, digest: str) -> ClipResult:
        output: Path = plan.output  # type: ignore[attr-defined]
        if segment_id == "b:0":
            raise RuntimeError("boom")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"clip")
        return ClipResult(segment_id, output, digest)

    monkeypatch.setattr("autocut.core.export.export_one", flaky)
    manifest = project(tmp_path)
    add_file(manifest, "a", minutes=0)
    add_file(manifest, "b", minutes=10)
    add_segment(manifest, "a:0", "a", order=1)
    add_segment(manifest, "b:0", "b", order=2)

    result = export_clips(manifest, one_worker(AutocutConfig()))

    assert result.exported == 1
    assert result.failed == 1
    assert manifest.segments["a:0"].exported_path is not None
    b_error = manifest.segments["b:0"].export_error
    assert b_error is not None and b_error.startswith("worker failed:")


@pytest.mark.ffmpeg
def test_pool_worker_failure_is_isolated(tmp_path: Path, synthetic_dir: Path) -> None:
    """A real, spawn-visible failure: one clip's output directory already exists as a
    plain file, so ``Path.mkdir`` raises for real inside the worker, not by monkeypatch."""
    manifest = project(tmp_path)
    add_file(manifest, "a", path=synthetic_dir / "sharp_pan.mp4", minutes=0)
    add_file(manifest, "b", path=synthetic_dir / "sharp_pan.mp4", minutes=10)
    add_segment(manifest, "a:0", "a", order=1)
    add_segment(manifest, "b:0", "b", outcome="rejected", order=None, reason="x")
    config = AutocutConfig()
    config.analysis.workers = 4

    out_dir = Path(manifest.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / REJECTS_DIR).write_text("not a directory")

    result = export_clips(manifest, config, overrides=ExportOverrides(rejects=True))

    assert result.exported == 1, result.errors
    assert result.failed == 1
    a_segment = manifest.segments["a:0"]
    b_segment = manifest.segments["b:0"]
    assert a_segment.exported_path is not None and a_segment.exported_path.exists()
    assert b_segment.export_error is not None
    assert b_segment.export_error.startswith("worker failed:")


def test_a_missing_ffmpeg_is_reported_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = project(tmp_path)
    source = add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a")
    plan = plan_export(segment, source, manifest, AutocutConfig(), output=tmp_path / "out.mp4")

    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr("subprocess.run", missing)
    clip = export_one(plan, "a:0", "digest")

    assert clip.error == "ffmpeg not found on PATH"


# --- probe helpers -----------------------------------------------------------


def probe_duration(path: Path) -> float:
    return float(_ffprobe(path, "format=duration"))


def probe_streams(path: Path) -> list[str]:
    return [line for line in _ffprobe(path, "stream=codec_type").splitlines() if line]


def probe_video(path: Path) -> dict[str, str]:
    keys = ("width", "height", "pix_fmt", "r_frame_rate")
    values = _ffprobe(path, f"stream={','.join(keys)}", video_only=True).split(",")
    return dict(zip(keys, [value.strip() for value in values], strict=False))


def probe_rotation(path: Path) -> int:
    raw = _ffprobe(path, "stream_side_data=rotation", video_only=True).strip()
    return int(float(raw)) if raw else 0


def _ffprobe(path: Path, entries: str, video_only: bool = False) -> str:
    import subprocess

    command = ["ffprobe", "-v", "error"]
    if video_only:
        command += ["-select_streams", "v:0"]
    command += ["-show_entries", entries, "-of", "csv=p=0", str(path)]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def test_beat_bounds_win_over_the_target_duration(tmp_path: Path) -> None:
    """The scenario from the spec: 2.2 s assigned, 2.0 s from beat sync, 2.0 s exported."""
    manifest = project(tmp_path)
    source = add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a", center=3.0, duration=2.2)
    segment.final_start_s = 2.0
    segment.final_end_s = 4.0

    plan = plan_export(segment, source, manifest, AutocutConfig())

    assert plan.source_start_s == pytest.approx(2.0)
    assert plan.source_duration_s == pytest.approx(2.0)
    assert plan.out_duration_s == pytest.approx(2.0)


def test_without_beat_bounds_the_target_duration_still_decides(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    source = add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a", center=3.0, duration=2.2)

    plan = plan_export(segment, source, manifest, AutocutConfig())

    assert plan.out_duration_s == pytest.approx(2.2)
    assert plan.source_start_s == pytest.approx(1.9)


def test_half_written_beat_bounds_are_ignored(tmp_path: Path) -> None:
    """A start with no end, or an end before its start, is not a window."""
    manifest = project(tmp_path)
    source = add_file(manifest, "a")
    segment = add_segment(manifest, "a:0", "a", center=3.0, duration=2.2)
    segment.final_start_s = 2.0

    config = AutocutConfig()
    assert plan_export(segment, source, manifest, config).out_duration_s == pytest.approx(2.2)

    segment.final_end_s = 1.0
    assert plan_export(segment, source, manifest, config).out_duration_s == pytest.approx(2.2)

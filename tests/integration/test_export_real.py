"""Export over the real Sardinia footage. Skips unless AUTOCUT_REAL_FOOTAGE is set.

Synthetic fixtures verify mechanics only (ADR 8). What only real footage answers here
is whether the cut lands where the window says on 4K H.264 and 10-bit HEVC with a
proxy attached, whether the telemetry streams stay out of the outputs, and whether the
rotated phone clips come out upright.

The fixture selects a handful of clips rather than the whole edit, because a full
40 clip export takes four minutes and nothing in this module gets more true at scale.
The numbers for the whole edit are recorded in the m2-export task list.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.analyze import analyze_files
from autocut.core.config import AutocutConfig
from autocut.core.export import export_clips
from autocut.core.ffmpeg_cmd import ExportOverrides
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest, Segment
from autocut.core.naming import SELECTS_DIR, STALE_DIR
from autocut.core.select import SelectionOverrides, select_clips

pytestmark = [pytest.mark.real_footage, pytest.mark.ffmpeg]

CLIPS = 6


@pytest.fixture(scope="module")
def exported(
    real_footage_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Manifest, AutocutConfig]:
    """Analyze, select a handful and export them once, shared by every test here."""
    workspace = tmp_path_factory.mktemp("real-export")
    config = AutocutConfig()
    # A cache of its own, so the test neither reads nor pollutes the developer's.
    config.cache.dir = workspace / "cache"
    config.analysis.workers = 4
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now,
        updated_at=now,
        sources=[real_footage_dir],
        output_dir=workspace / "edit",
    )
    manifest.files = {source.id: source for source in ingest([real_footage_dir], config)}
    analyze_files(manifest, config, lambda event: None)
    select_clips(manifest, config, SelectionOverrides(max_clips=CLIPS))
    export_clips(manifest, config)
    return manifest, config


def selected(manifest: Manifest) -> list[Segment]:
    return [s for s in manifest.segments.values() if s.outcome == "selected"]


def ffprobe(path: Path, entries: str, video_only: bool = False) -> str:
    command = ["ffprobe", "-v", "error"]
    if video_only:
        command += ["-select_streams", "v:0"]
    command += ["-show_entries", entries, "-of", "csv=p=0", str(path)]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()


def test_every_selected_clip_has_an_output(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, _ = exported
    chosen = selected(manifest)
    assert len(chosen) == CLIPS
    for segment in chosen:
        assert segment.export_error is None, segment.export_error
        assert segment.exported_path is not None
        assert segment.exported_path.exists()
        assert segment.exported_path.stat().st_size > 0


def test_the_cut_lands_within_one_frame_of_the_window(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """The exact duration requirement in specs/clip-export, on real 4K sources.

    The video stream is measured rather than the container. A container's duration is
    the longest of its streams, and an AAC frame holds 21.3 ms that is not split, so a
    clip that keeps its audio reads up to one audio frame long however exact the cut
    was. On the Sardinia phone clip that is 3.04 against a video stream of exactly
    3.000000, and at a 50 fps target one frame is 20 ms, so the container reading would
    fail a cut that is in fact frame perfect.
    """
    manifest, _ = exported
    target = manifest.export.target_fps or 25.0
    for segment in selected(manifest):
        assert segment.exported_path is not None
        duration = float(ffprobe(segment.exported_path, "stream=duration", video_only=True))
        expected = segment.target_duration_s or 0.0
        assert abs(duration - expected) <= 1 / target, segment.exported_path.name


def test_every_output_is_at_the_target_frame_rate(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, _ = exported
    target = manifest.export.target_fps
    assert target
    for segment in selected(manifest):
        assert segment.exported_path is not None
        rate = ffprobe(segment.exported_path, "stream=r_frame_rate", video_only=True)
        numerator, _, denominator = rate.partition("/")
        assert float(numerator) / float(denominator or 1) == pytest.approx(target)


def test_no_output_is_upscaled(exported: tuple[Manifest, AutocutConfig]) -> None:
    manifest, config = exported
    for segment in selected(manifest):
        source = manifest.files[segment.file_id]
        assert segment.exported_path is not None
        width, height = (
            int(value)
            for value in ffprobe(
                segment.exported_path, "stream=width,height", video_only=True
            ).split(",")
        )
        assert width <= max(source.display_width, 1)
        assert height <= max(source.display_height, 1)
        assert width <= config.export.max_width
        assert height <= config.export.max_height


def test_every_output_is_8_bit_yuv420p(exported: tuple[Manifest, AutocutConfig]) -> None:
    """The Action 4 files are 10-bit HEVC; CapCut should not have to convert on import."""
    manifest, _ = exported
    for segment in selected(manifest):
        assert segment.exported_path is not None
        assert ffprobe(segment.exported_path, "stream=pix_fmt", video_only=True) == "yuv420p"


def test_no_output_carries_telemetry_or_data_streams(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """DJI clips hold telemetry as a subtitle stream and the Action 4 adds data streams.

    An Action 4 source carries `djmd`, `dbgi` and a timecode track, plus an embedded
    still image as a second video stream. The output is one video stream and, when the
    class keeps it, one audio stream.
    """
    manifest, _ = exported
    for segment in selected(manifest):
        assert segment.exported_path is not None
        kinds = ffprobe(segment.exported_path, "stream=codec_type").splitlines()
        assert kinds.count("video") == 1
        assert "subtitle" not in kinds
        assert "data" not in kinds


def test_no_output_carries_rotation_metadata(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """Rotation side data is applied at decode, so no editor has to guess."""
    manifest, _ = exported
    for segment in selected(manifest):
        assert segment.exported_path is not None
        rotation = ffprobe(segment.exported_path, "stream_side_data=rotation", video_only=True)
        assert rotation in ("", "0", "0.000000"), segment.exported_path.name


def test_drone_clips_come_out_silent(exported: tuple[Manifest, AutocutConfig]) -> None:
    manifest, _ = exported
    drone = [s for s in selected(manifest) if manifest.files[s.file_id].source_class == "drone"]
    if not drone:
        pytest.skip("no drone clip in this selection")
    for segment in drone:
        assert segment.exported_path is not None
        assert "audio" not in ffprobe(segment.exported_path, "stream=codec_type").splitlines()


def test_names_sort_into_selection_order(exported: tuple[Manifest, AutocutConfig]) -> None:
    """CapCut imports alphabetically, which is the only reason the index exists."""
    manifest, _ = exported
    by_order = sorted(selected(manifest), key=lambda s: s.order or 0)
    names = [s.exported_path.name for s in by_order if s.exported_path]
    assert names == sorted(names)
    for index, name in enumerate(names, start=1):
        assert name.startswith(f"{index:03d}_")


def test_the_names_carry_the_class_and_the_day(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    manifest, _ = exported
    for segment in selected(manifest):
        source = manifest.files[segment.file_id]
        assert segment.exported_path is not None
        parts = segment.exported_path.stem.split("_")
        assert parts[1].startswith("2025"), segment.exported_path.name
        assert source.source_class in parts


def test_vertical_phone_clips_never_reach_the_edit(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """The default strategy excludes them, and the report has to say which and why."""
    manifest, config = exported
    assert config.export.vertical_strategy == "exclude"
    for segment in selected(manifest):
        assert not manifest.files[segment.file_id].is_vertical
    excluded = [s for s in manifest.segments.values() if s.reason == "vertical"]
    assert excluded, "the Sardinia set holds vertical phone clips"
    for segment in excluded:
        assert segment.outcome == "candidate"
        assert manifest.files[segment.file_id].is_vertical


def test_a_second_export_encodes_nothing(exported: tuple[Manifest, AutocutConfig]) -> None:
    """The whole point of the fingerprint: a re-run of a finished export is free."""
    manifest, config = exported
    result = export_clips(manifest, config)
    assert result.exported == 0
    assert result.skipped == CLIPS
    assert result.stale_moved == 0


def test_changing_the_frame_rate_re_encodes_every_clip(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """A settings change has to reach every clip, in place.

    Nothing goes stale here. The name carries the order, the day, the class and the
    output duration, none of which a frame rate change touches, so clip 001 is still
    clip 001 and its file is simply rewritten. The stale folder is for clips a later
    ``select`` dropped, which is the case the next test covers.
    """
    manifest, config = exported
    before = {s.exported_path for s in selected(manifest) if s.exported_path}
    target = manifest.export.target_fps or 25.0

    result = export_clips(manifest, config, overrides=ExportOverrides(fps=target / 2))

    assert result.exported == CLIPS
    assert result.stale_moved == 0
    for path in before:
        assert path.exists()
    for segment in selected(manifest):
        assert segment.exported_path is not None
        rate = ffprobe(segment.exported_path, "stream=r_frame_rate", video_only=True)
        numerator, _, denominator = rate.partition("/")
        assert float(numerator) / float(denominator or 1) == pytest.approx(target / 2)


def test_a_deselected_clip_leaves_its_output_in_stale(
    exported: tuple[Manifest, AutocutConfig],
) -> None:
    """The reselect scenario in specs/output-naming, on real files."""
    manifest, config = exported
    dropped = sorted(selected(manifest), key=lambda s: s.order or 0)[-1]
    gone = dropped.exported_path
    assert gone is not None and gone.exists()
    dropped.outcome = "candidate"
    dropped.order = None
    dropped.exported_path = None
    dropped.export_fingerprint = None

    result = export_clips(manifest, config)

    assert result.stale_moved == 1
    assert not gone.exists()
    assert (Path(manifest.output_dir) / SELECTS_DIR / STALE_DIR / gone.name).exists()

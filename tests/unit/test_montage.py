"""Rendering the edit as one file: the windows, the fingerprint, the index, the concat."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressEvent
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile
from autocut.core.montage import (
    INDEX_FILENAME,
    MONTAGE_FILENAME,
    MontageCancelled,
    build_montage,
    clear_preview,
    clip_at,
    concat_command,
    is_current,
    montage_fingerprint,
    part_command,
    parts_dir,
    preview_dir,
    probe_duration,
    read_index,
    render_parts,
    selected_in_order,
    write_index,
)

CLIPS = ("sharp_pan.mp4", "static.mp4", "multishot.mp4")


def settings(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    return config


def project(tmp_path: Path, clips: tuple[str, ...], synthetic: Path) -> Manifest:
    """A selected project over real synthetic files, so ffmpeg has something to read."""
    now = datetime.now(UTC)
    out = tmp_path / "edit"
    out.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(created_at=now, updated_at=now, sources=[synthetic], output_dir=out)
    for index, name in enumerate(clips):
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


# --- the commands, without running them ---------------------------------------


def test_a_part_is_small_silent_and_fixed_rate(tmp_path: Path, synthetic_dir: Path) -> None:
    from dataclasses import replace

    from autocut.core.ffmpeg_cmd import plan_export

    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    segment = manifest.segments["f0:0"]
    source = manifest.files["f0"]
    plan = replace(plan_export(segment, source, manifest, config), source=source.path)

    command = part_command(plan, 360, config, tmp_path / "part.mp4")

    assert "-an" in command
    assert "scale=-2:360:flags=fast_bilinear,fps=25" in command
    assert command[command.index("-preset") + 1] == "ultrafast"
    assert command[command.index("-crf") + 1] == "28"
    assert command[command.index("-frames:v") + 1] == str(plan.out_frames)
    assert "-c:v" in command and command[command.index("-c:v") + 1] == "libx264"


def test_a_slowed_clip_is_slowed_in_the_montage_too(tmp_path: Path, synthetic_dir: Path) -> None:
    """A montage that ran a 100 fps clip at speed would show an edit nobody exported."""
    from dataclasses import replace

    from autocut.core.ffmpeg_cmd import plan_export

    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    plan = replace(
        plan_export(manifest.segments["f0:0"], manifest.files["f0"], manifest, config),
        slow_motion_ratio=2,
    )

    command = part_command(plan, 360, config, tmp_path / "part.mp4")

    chain = command[command.index("-vf") + 1]
    assert chain.startswith("setpts=2*PTS,")


def test_the_concat_copies_the_video_and_re_encodes_the_track(tmp_path: Path) -> None:
    with_track = concat_command(
        tmp_path / "parts.txt", tmp_path / "t.mp3", tmp_path / "m.mp4", 12.5
    )
    without = concat_command(tmp_path / "parts.txt", None, tmp_path / "m.mp4", 12.5)

    assert with_track[with_track.index("-c:v") + 1] == "copy"
    assert with_track[with_track.index("-c:a") + 1] == "aac"
    assert "-an" in without
    assert "-dn" in with_track
    # The mp4 muxer writes a timecode track from the copied stream unless told not to.
    assert with_track[with_track.index("-write_tmcd") + 1] == "0"


def test_the_video_length_wins_over_the_track_length(tmp_path: Path) -> None:
    """Measured on the real project: ``-shortest`` cut a 77 s edit down to a 20 s track.

    So the audio is padded and the output is cut to the montage's own duration. A
    short track leaves the rest of the edit silent, which is the honest outcome, and a
    long one is trimmed.
    """
    command = concat_command(tmp_path / "parts.txt", tmp_path / "t.mp3", tmp_path / "m.mp4", 77.3)

    assert "-shortest" not in command
    assert command[command.index("-af") + 1] == "apad"
    assert command[command.index("-t") + 1] == "77.300"


def test_the_parts_list_escapes_a_quote_in_a_path(tmp_path: Path, synthetic_dir: Path) -> None:
    """The concat demuxer doubles single quotes, and a folder may hold one."""
    from autocut.core.montage import Part, concat_montage

    odd = tmp_path / "it's here"
    odd.mkdir()
    part = odd / "001.mp4"
    part.write_bytes(b"not a video")

    concat_montage([Part(1, "f0:0", part, 1.0)], None, tmp_path / "montage.mp4")

    listing = (tmp_path / "parts.txt").read_text(encoding="utf-8")
    assert "it''s here" in listing


# --- the fingerprint ----------------------------------------------------------


def test_the_fingerprint_covers_the_edit(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)

    first = montage_fingerprint(manifest, config, None)

    assert first == montage_fingerprint(manifest, config, None)
    manifest.segments["f1:0"].outcome = "candidate"
    assert montage_fingerprint(manifest, config, None) != first


def test_a_changed_bound_changes_the_fingerprint(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    before = montage_fingerprint(manifest, config, None)

    manifest.segments["f0:0"].user_start_s = 1.0
    manifest.segments["f0:0"].user_end_s = 2.0

    assert montage_fingerprint(manifest, config, None) != before


def test_a_changed_order_changes_the_fingerprint(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    before = montage_fingerprint(manifest, config, None)

    manifest.segments["f0:0"].order = 3
    manifest.segments["f2:0"].order = 1

    assert montage_fingerprint(manifest, config, None) != before


def test_the_track_is_part_of_the_fingerprint(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    track = tmp_path / "track.mp3"
    track.write_bytes(b"first")

    without = montage_fingerprint(manifest, config, None)
    with_track = montage_fingerprint(manifest, config, track)
    track.write_bytes(b"a different, longer take")
    replaced = montage_fingerprint(manifest, config, track)

    assert len({without, with_track, replaced}) == 3


def test_the_height_and_the_preset_are_part_of_it(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    before = montage_fingerprint(manifest, config, None)

    config.gui.montage_height = 540

    assert montage_fingerprint(manifest, config, None) != before


def test_nothing_built_is_not_current(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)

    assert not is_current(manifest, config, None)


def test_a_montage_whose_file_is_gone_is_not_current(tmp_path: Path, synthetic_dir: Path) -> None:
    """The manifest is not evidence that a file exists."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    manifest.preview.fingerprint = montage_fingerprint(manifest, config, None)
    manifest.preview.path = tmp_path / "gone.mp4"

    assert not is_current(manifest, config, None)


# --- the index ----------------------------------------------------------------


def test_the_index_lists_cumulative_spans(tmp_path: Path, synthetic_dir: Path) -> None:
    from autocut.core.montage import Part

    manifest = project(tmp_path, CLIPS, synthetic_dir)
    parts = [
        Part(1, "f0:0", tmp_path / "a.mp4", 1.0, start_s=0.0),
        Part(2, "f1:0", tmp_path / "b.mp4", 2.0, start_s=1.0),
        Part(3, "f2:0", tmp_path / "c.mp4", 1.5, start_s=3.0),
    ]

    path = write_index(manifest, parts, tmp_path / MONTAGE_FILENAME)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == INDEX_FILENAME
    assert payload["duration_s"] == pytest.approx(4.5)
    assert [clip["segment_id"] for clip in payload["clips"]] == ["f0:0", "f1:0", "f2:0"]
    assert payload["clips"][1]["start_s"] == pytest.approx(1.0)
    assert payload["clips"][1]["end_s"] == pytest.approx(3.0)


def test_the_index_reads_back(tmp_path: Path, synthetic_dir: Path) -> None:
    from autocut.core.montage import Part

    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)
    written = [
        Part(1, "f0:0", tmp_path / "a.mp4", 1.0, start_s=0.0),
        Part(2, "f1:0", tmp_path / "b.mp4", 2.0, start_s=1.0),
    ]
    path = write_index(manifest, written, tmp_path / MONTAGE_FILENAME)

    parts = read_index(path)

    assert [part.segment_id for part in parts] == ["f0:0", "f1:0"]
    assert parts[1].end_s == pytest.approx(3.0)


def test_a_missing_or_broken_index_is_no_parts(tmp_path: Path) -> None:
    assert read_index(tmp_path / "nothing.json") == []
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert read_index(broken) == []


def test_a_time_maps_to_the_clip_playing_then(tmp_path: Path) -> None:
    """The scenario from the spec: 12.4 s falls in clip 5, which spans 10 to 14."""
    from autocut.core.montage import Part

    parts = [
        Part(4, "f3:0", tmp_path / "d.mp4", 10.0, start_s=0.0),
        Part(5, "f4:0", tmp_path / "e.mp4", 4.0, start_s=10.0),
        Part(6, "f5:0", tmp_path / "f.mp4", 2.0, start_s=14.0),
    ]

    assert clip_at(parts, 12.4) is parts[1]
    assert clip_at(parts, 0.0) is parts[0]
    assert clip_at(parts, 14.0) is parts[2]
    # Past the end is the last clip, which is where a finished playback sits.
    assert clip_at(parts, 99.0) is parts[2]
    assert clip_at([], 1.0) is None


def test_the_order_is_the_edit_order(tmp_path: Path, synthetic_dir: Path) -> None:
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    manifest.segments["f0:0"].order = 3
    manifest.segments["f2:0"].order = 1

    assert [s.id for s in selected_in_order(manifest)] == ["f2:0", "f1:0", "f0:0"]


# --- rendering ----------------------------------------------------------------


@pytest.mark.ffmpeg
def test_the_montage_lasts_the_sum_of_its_parts(tmp_path: Path, synthetic_dir: Path) -> None:
    """The scenario from the spec, at three clips rather than twenty-nine."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)

    result = build_montage(manifest, config)

    assert result.ok, result.errors
    assert result.path is not None
    assert len(result.parts) == 3
    total = sum(part.duration_s for part in result.parts)
    # Within one frame at 25 fps, which is the tolerance the design asks for.
    assert result.duration_s == pytest.approx(total, abs=0.04)
    assert result.duration_s == pytest.approx(3.0, abs=0.2)


@pytest.mark.ffmpeg
def test_the_montage_is_one_video_stream_at_the_asked_height(
    tmp_path: Path, synthetic_dir: Path
) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)

    result = build_montage(manifest, config)

    assert result.path is not None
    streams = _streams(result.path)
    assert [stream["codec_type"] for stream in streams] == ["video"]
    assert streams[0]["height"] == 360
    assert int(str(streams[0]["width"])) % 2 == 0


@pytest.mark.ffmpeg
def test_a_track_becomes_the_montage_audio(tmp_path: Path, synthetic_dir: Path) -> None:
    """The scenario from the spec: with a track loaded the montage has it as audio."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)

    result = build_montage(manifest, config, track=synthetic_dir / "click_120bpm.wav")

    assert result.path is not None
    kinds = [stream["codec_type"] for stream in _streams(result.path)]
    assert kinds.count("video") == 1
    assert kinds.count("audio") == 1
    # Video and audio and nothing else: no timecode track, no data stream.
    assert set(kinds) == {"video", "audio"}
    assert result.has_audio
    assert manifest.preview.has_audio


@pytest.mark.ffmpeg
@pytest.mark.ffmpeg
def test_a_track_longer_than_the_montage_is_trimmed(tmp_path: Path, synthetic_dir: Path) -> None:
    """Two seconds of clips must not become twenty of the track."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)

    result = build_montage(manifest, config, track=synthetic_dir / "click_120bpm.wav")

    assert result.duration_s == pytest.approx(2.0, abs=0.3)


@pytest.mark.ffmpeg
def test_a_track_shorter_than_the_montage_leaves_the_edit_whole(
    tmp_path: Path, synthetic_dir: Path
) -> None:
    """The bug the real footage found: the edit is the montage, not the track.

    The click fixture is 20 s and the Sardinia edit is 77 s, and ``-shortest`` threw
    away 57 s of it. The rest of the montage is silent instead.
    """
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    for index, segment in enumerate(manifest.segments.values()):
        segment.target_duration_s = 5.0
        segment.order = index + 1
    short = tmp_path / "short.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            str(short),
        ],
        check=True,
    )

    result = build_montage(manifest, config, track=short)

    assert result.ok, result.errors
    expected = sum(part.duration_s for part in result.parts)
    assert expected == pytest.approx(15.0, abs=0.3)
    assert result.duration_s == pytest.approx(expected, abs=0.2)
    assert result.has_audio


@pytest.mark.ffmpeg
def test_without_a_track_there_is_no_audio_stream(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)

    result = build_montage(manifest, config)

    assert result.path is not None
    assert all(stream["codec_type"] != "audio" for stream in _streams(result.path))
    assert not result.has_audio


@pytest.mark.ffmpeg
def test_a_second_call_renders_nothing(tmp_path: Path, synthetic_dir: Path) -> None:
    """Pressing Play all twice on an untouched edit has to cost nothing."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)
    first = build_montage(manifest, config)
    assert first.path is not None
    stamp = first.path.stat().st_mtime_ns

    second = build_montage(manifest, config)

    assert second.reused_montage
    assert second.rendered == 0
    assert second.path == first.path
    assert first.path.stat().st_mtime_ns == stamp
    assert len(second.parts) == 2


@pytest.mark.ffmpeg
def test_rejecting_one_clip_re_renders_only_the_concat(tmp_path: Path, synthetic_dir: Path) -> None:
    """The scenario from the spec, and the reason parts carry their own fingerprint."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    first = build_montage(manifest, config)
    assert first.rendered == 3
    kept = {part.segment_id: part.path.stat().st_mtime_ns for part in first.parts}

    dropped = manifest.segments["f1:0"]
    dropped.outcome = "candidate"
    dropped.order = None
    second = build_montage(manifest, config)

    assert second.ok, second.errors
    assert second.rendered == 0
    assert second.reused == 2
    assert [part.segment_id for part in second.parts] == ["f0:0", "f2:0"]
    for part in second.parts:
        assert part.path.stat().st_mtime_ns == kept[part.segment_id]
    # The part nobody uses any more is gone, and the two kept files are all there is.
    assert len(list(parts_dir(manifest).iterdir())) == 2


@pytest.mark.ffmpeg
def test_a_changed_bound_re_renders_that_part_only(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    build_montage(manifest, config)

    manifest.segments["f0:0"].user_start_s = 1.0
    manifest.segments["f0:0"].user_end_s = 2.5
    second = build_montage(manifest, config)

    assert second.rendered == 1
    assert second.reused == 2


@pytest.mark.ffmpeg
def test_the_render_reports_one_event_per_clip(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    events: list[ProgressEvent] = []

    build_montage(manifest, config, progress=events.append)

    montage_events = [event for event in events if event.extra.get("montage_part")]
    assert [event.current for event in montage_events] == [1, 2, 3]
    assert all(event.total == 3 for event in montage_events)
    assert all(event.stage == "export" for event in montage_events)


@pytest.mark.ffmpeg
def test_a_cancel_between_clips_leaves_the_previous_montage_valid(
    tmp_path: Path, synthetic_dir: Path
) -> None:
    """The scenario from the spec: nothing partial is recorded and the old one stands."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    first = build_montage(manifest, config)
    assert first.ok
    good_fingerprint = manifest.preview.fingerprint

    manifest.segments["f0:0"].user_start_s = 2.0
    manifest.segments["f0:0"].user_end_s = 3.0

    def cancel_after_two(event: ProgressEvent) -> None:
        if event.current >= 2:
            raise MontageCancelled("stopped")

    with pytest.raises(MontageCancelled):
        build_montage(manifest, config, progress=cancel_after_two)

    # The manifest still points at the montage that was finished.
    assert manifest.preview.fingerprint == good_fingerprint
    assert manifest.preview.path is not None
    assert Path(manifest.preview.path).exists()


@pytest.mark.ffmpeg
def test_the_montage_uses_the_hand_set_window(tmp_path: Path, synthetic_dir: Path) -> None:
    """A preview that cut somewhere else than the export would be worse than none."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    segment = manifest.segments["f0:0"]
    segment.user_start_s = 1.0
    segment.user_end_s = 3.4

    result = build_montage(manifest, config)

    assert result.parts
    assert result.parts[0].duration_s == pytest.approx(2.4, abs=0.1)


@pytest.mark.ffmpeg
def test_the_montage_uses_the_beat_bounds(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    segment = manifest.segments["f0:0"]
    segment.final_start_s = 0.5
    segment.final_end_s = 2.5
    segment.beats = 4

    result = build_montage(manifest, config)

    assert result.parts[0].duration_s == pytest.approx(2.0, abs=0.1)


@pytest.mark.ffmpeg
def test_the_manifest_records_the_montage(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)

    result = build_montage(manifest, config)

    assert manifest.preview.fingerprint == result.fingerprint
    assert manifest.preview.path == result.path
    assert manifest.preview.index_path == result.index_path
    assert manifest.preview.clips == 2
    assert manifest.preview.duration_s == pytest.approx(result.duration_s)
    assert manifest.preview.built_at is not None
    assert is_current(manifest, config, None)


def test_nothing_selected_is_not_a_montage(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    manifest.segments["f0:0"].outcome = "candidate"

    result = build_montage(manifest, config)

    assert result.path is None
    assert result.skipped_reason == "nothing is selected"


@pytest.mark.ffmpeg
def test_an_unreadable_source_is_reported_and_the_others_are_used(
    tmp_path: Path, synthetic_dir: Path
) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)
    manifest.files["f1"].path = tmp_path / "gone.mp4"

    result = build_montage(manifest, config)

    assert result.ok is False or result.errors
    assert any(segment_id == "f1:0" for segment_id, _error in result.errors)
    assert [part.segment_id for part in result.parts] == ["f0:0", "f2:0"]
    assert result.path is not None


@pytest.mark.ffmpeg
def test_clearing_the_preview_removes_every_file(tmp_path: Path, synthetic_dir: Path) -> None:
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:2], synthetic_dir)
    build_montage(manifest, config)
    assert preview_dir(manifest).is_dir()

    removed = clear_preview(manifest)

    assert removed >= 3  # two parts, the montage, the index and the list file
    assert not preview_dir(manifest).exists()
    assert manifest.preview.fingerprint is None
    assert not is_current(manifest, config, None)


def test_clearing_nothing_is_not_an_error(tmp_path: Path, synthetic_dir: Path) -> None:
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)

    assert clear_preview(manifest) == 0


@pytest.mark.ffmpeg
def test_the_parts_are_read_from_the_proxy_when_there_is_one(
    tmp_path: Path, synthetic_dir: Path
) -> None:
    """A 360 px montage has nothing to gain from a 4K original."""
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS[:1], synthetic_dir)
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes((synthetic_dir / "static.mp4").read_bytes())
    manifest.files["f0"].proxy_path = proxy
    before = montage_fingerprint(manifest, config, None)

    result = build_montage(manifest, config)

    assert result.ok, result.errors
    # The proxy's identity is in the fingerprint, so touching it invalidates the montage.
    proxy.write_bytes((synthetic_dir / "sharp_pan.mp4").read_bytes())
    assert montage_fingerprint(manifest, config, None) != before


@pytest.mark.ffmpeg
def test_the_parts_are_named_by_what_they_are(tmp_path: Path, synthetic_dir: Path) -> None:
    """Not by their position: dropping clip two must not rename clip three.

    The first version put the edit position in the file name, so rejecting one clip
    renamed every part after it and re-rendered them all, which is exactly what the
    per part fingerprint is there to prevent.
    """
    config = settings(tmp_path)
    manifest = project(tmp_path, CLIPS, synthetic_dir)

    parts, errors = render_parts(manifest, config)

    assert not errors
    names = [part.path.name for part in parts]
    assert all(name.endswith(".mp4") for name in names)
    assert not any(name.startswith(("001", "002", "003")) for name in names)
    assert len(set(names)) == 3


def test_a_missing_file_probes_as_no_duration(tmp_path: Path) -> None:
    assert probe_duration(tmp_path / "nothing.mp4") == 0.0


def _streams(path: Path) -> list[dict[str, object]]:
    """Every stream ffprobe reports, as dictionaries."""
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    streams: list[dict[str, object]] = payload.get("streams", [])
    return streams

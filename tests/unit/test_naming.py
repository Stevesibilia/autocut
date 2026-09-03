"""Output names and the folder layout that carries the order into CapCut."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from autocut.core.manifest import Segment, SourceFile
from autocut.core.naming import (
    DEFAULT_TAG,
    clip_date,
    clip_name,
    clip_tag,
    sanitize,
    stale_outputs,
)


def source(
    file_id: str = "a",
    source_class: str = "drone",
    created: datetime | None = datetime(2026, 8, 12, 10, 30, tzinfo=UTC),
) -> SourceFile:
    return SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=30.0,
        width=3840,
        height=2160,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
        creation_time=created,
    )


def segment(
    segment_id: str = "a:0",
    file_id: str = "a",
    center: float = 10.0,
    tags: list[str] | None = None,
) -> Segment:
    return Segment(
        id=segment_id,
        file_id=file_id,
        start_s=5.0,
        end_s=20.0,
        best_center_s=center,
        target_duration_s=4.0,
        outcome="selected",
        order=12,
        tags=tags or [],
    )


def test_the_example_name_from_the_spec() -> None:
    """The 12th clip, drone, 2026-08-12, four seconds, no tags."""
    name = clip_name(segment(), source(), 12, 4.0)
    assert name == "012_20260812_drone_clip_4.0s.mp4"


def test_a_semantic_tag_replaces_the_placeholder() -> None:
    name = clip_name(segment(tags=["sunset"]), source(), 12, 4.0)
    assert name == "012_20260812_drone_sunset_4.0s.mp4"


def test_an_explicit_tag_wins_over_the_segment_tags() -> None:
    """The rejects folder passes the reason in place of the tag."""
    name = clip_name(segment(tags=["sunset"]), source(), 3, 2.0, "low_altitude")
    assert name == "003_20260812_drone_low_altitude_2.0s.mp4"


def test_alphabetical_order_is_selection_order() -> None:
    names = [clip_name(segment(), source(), order, 3.0) for order in range(1, 46)]
    assert names == sorted(names)
    assert names[0].startswith("001_")
    assert names[-1].startswith("045_")


def test_the_index_is_padded_to_three_digits() -> None:
    assert clip_name(segment(), source(), 7, 3.0).startswith("007_")
    assert clip_name(segment(), source(), 123, 3.0).startswith("123_")


def test_the_date_is_the_local_date_of_the_clip() -> None:
    """A clip filmed late in the evening belongs to that evening, wherever it is read.

    The instant is built from a local wall clock time so the assertion holds in any
    timezone the test runs in, which is the same reason the name uses local time: the
    user reads these names against the days of a holiday.
    """
    late_local = datetime(2026, 8, 12, 23, 30).astimezone()
    assert clip_date(segment(center=0.0), source(created=late_local)) == "20260812"


def test_the_window_offset_counts_towards_the_date() -> None:
    """The date is the moment of the clip, not of the file it was cut from."""
    before_midnight = datetime(2026, 8, 12, 23, 59, 30).astimezone()
    midnight = source(created=before_midnight)
    assert clip_date(segment(center=0.0), midnight) == "20260812"
    assert clip_date(segment(center=120.0), midnight) == "20260813"


def test_a_file_without_a_timestamp_gets_zeros() -> None:
    """Synthetic clips from lavfi have no creation time and must still get a name."""
    assert clip_date(segment(), source(created=None)) == "00000000"
    assert clip_name(segment(), source(created=None), 1, 3.0).startswith("001_00000000_")


def test_the_duration_carries_one_decimal() -> None:
    assert "_2.5s.mp4" in clip_name(segment(), source(), 1, 2.5)
    assert "_3.0s.mp4" in clip_name(segment(), source(), 1, 3.0)
    assert "_10.0s.mp4" in clip_name(segment(), source(), 1, 9.96)


def test_a_tag_is_reduced_to_something_a_filesystem_accepts() -> None:
    assert sanitize("Beach / Sunset!") == "beach_sunset"
    assert sanitize("Città") == "citt"
    assert sanitize("...") == DEFAULT_TAG
    assert sanitize("") == DEFAULT_TAG


def test_the_tag_falls_back_to_the_placeholder() -> None:
    assert clip_tag(segment()) == DEFAULT_TAG
    assert clip_tag(segment(tags=["Aerial Sunset", "beach"])) == "aerial_sunset"


def test_stale_detection_finds_what_no_longer_belongs(tmp_path: Path) -> None:
    selects = tmp_path / "_selects"
    selects.mkdir()
    for name in ("001_a.mp4", "002_b.mp4", "099_gone.mp4"):
        (selects / name).write_bytes(b"")
    stale = stale_outputs(selects, {"001_a.mp4", "002_b.mp4"})
    assert [path.name for path in stale] == ["099_gone.mp4"]


def test_stale_detection_leaves_directories_and_dotfiles_alone(tmp_path: Path) -> None:
    """The stale folder itself lives in _selects and must not be swept into itself."""
    selects = tmp_path / "_selects"
    (selects / "_stale").mkdir(parents=True)
    (selects / "_stale" / "old.mp4").write_bytes(b"")
    (selects / ".DS_Store").write_bytes(b"")
    (selects / "001_a.mp4").write_bytes(b"")
    assert stale_outputs(selects, {"001_a.mp4"}) == []


def test_stale_detection_on_a_folder_that_does_not_exist_yet(tmp_path: Path) -> None:
    assert stale_outputs(tmp_path / "_selects", {"001_a.mp4"}) == []

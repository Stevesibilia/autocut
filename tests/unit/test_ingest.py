"""Scanning, proxy discovery and the ordered ingest over the synthetic fixtures."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressEvent
from autocut.core.ingest import (
    _chronological_key,
    find_proxy,
    ingest,
    physical_cores,
    scan,
)
from autocut.core.manifest import SourceFile


def touch(path: Path, payload: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_scan_of_a_mixed_folder(tmp_path: Path) -> None:
    touch(tmp_path / "DJI_0744.MP4")
    touch(tmp_path / "DJI_0001_D.MP4")
    touch(tmp_path / "DJI_0001_D.LRF")
    touch(tmp_path / "notes.txt")
    touch(tmp_path / "DJI_0757.MP4.part")
    names = [item.path.name for item in scan([tmp_path])]
    assert names == ["DJI_0001_D.MP4", "DJI_0744.MP4"]


def test_scan_skips_hidden_files_and_folders(tmp_path: Path) -> None:
    touch(tmp_path / "keep.mp4")
    touch(tmp_path / ".hidden.mp4")
    touch(tmp_path / ".cache" / "inside.mp4")
    assert [item.path.name for item in scan([tmp_path])] == ["keep.mp4"]


def test_scan_is_recursive_and_case_insensitive(tmp_path: Path) -> None:
    touch(tmp_path / "day1" / "a.MOV")
    touch(tmp_path / "day2" / "deeper" / "b.mkv")
    touch(tmp_path / "day2" / "c.InsV")
    assert sorted(item.path.name for item in scan([tmp_path])) == ["a.MOV", "b.mkv", "c.InsV"]


def test_scan_of_two_source_folders_keeps_both_roots(tmp_path: Path) -> None:
    first = touch(tmp_path / "one" / "a.mp4")
    second = touch(tmp_path / "two" / "sub" / "b.mp4")
    scanned = scan([tmp_path / "one", tmp_path / "two"])
    assert [item.path for item in scanned] == [first, second]
    assert [item.rel_path.as_posix() for item in scanned] == ["a.mp4", "sub/b.mp4"]


def test_find_proxy_matches_lrf_and_lrv_case_insensitively(tmp_path: Path) -> None:
    video = touch(tmp_path / "DJI_20250713122959_0194_D.MP4")
    proxy = touch(tmp_path / "DJI_20250713122959_0194_D.LRF")
    assert find_proxy(video) == proxy

    other = touch(tmp_path / "GX010001.MP4")
    lrv = touch(tmp_path / "gx010001.lrv")
    assert find_proxy(other) == lrv


def test_find_proxy_returns_none_when_disabled(tmp_path: Path) -> None:
    video = touch(tmp_path / "clip.MP4")
    touch(tmp_path / "clip.LRF")
    config = AutocutConfig()
    config.analysis.use_proxies = False
    assert find_proxy(video, config) is None
    assert find_proxy(video, AutocutConfig()) is not None


def test_find_proxy_returns_none_without_a_sibling(tmp_path: Path) -> None:
    assert find_proxy(touch(tmp_path / "alone.mp4")) is None


def test_physical_cores_is_at_least_one() -> None:
    assert physical_cores() >= 1


def source(name: str, created: datetime | None) -> SourceFile:
    return SourceFile(id=name, path=Path(f"/footage/{name}"), creation_time=created)


def test_chronological_order_across_devices() -> None:
    day = datetime(2025, 7, 14, tzinfo=UTC)
    files = [
        source("phone.mp4", day + timedelta(hours=13, minutes=39)),
        source("drone.mp4", day + timedelta(hours=13, minutes=37)),
        source("action.mp4", day + timedelta(hours=13, minutes=38)),
    ]
    assert [f.path.name for f in sorted(files, key=_chronological_key)] == [
        "drone.mp4",
        "action.mp4",
        "phone.mp4",
    ]


def test_ties_are_broken_by_path() -> None:
    day = datetime(2025, 7, 14, 13, 37, tzinfo=UTC)
    files = [source("b.mp4", day), source("a.mp4", day)]
    assert [f.path.name for f in sorted(files, key=_chronological_key)] == ["a.mp4", "b.mp4"]


@pytest.mark.ffmpeg
def test_ingest_over_the_synthetic_folder(synthetic_dir: Path) -> None:
    config = AutocutConfig()
    config.analysis.workers = 2
    events: list[ProgressEvent] = []
    captured = io.StringIO()

    with redirect_stdout(captured):
        files = ingest([synthetic_dir], config, events.append)

    expected = sorted(p.name for p in synthetic_dir.glob("*.mp4"))
    assert sorted(f.path.name for f in files) == expected
    # The core never prints; only the front ends do.
    assert captured.getvalue() == ""
    probe_events = [e for e in events if e.stage == "probe"]
    assert len(probe_events) == len(files)
    assert probe_events[-1].current == probe_events[-1].total == len(files)

    keys = {f.id for f in files}
    assert len(keys) == len(files)
    assert all(f.error is None for f in files)
    assert [f.path.name for f in files] == [
        f.path.name for f in sorted(files, key=_chronological_key)
    ]

    by_name = {f.path.name: f for f in files}
    assert by_name["drone_embedded_srt.mp4"].source_class == "drone"
    assert by_name["drone_embedded_srt.mp4"].telemetry == "dji_embedded_srt"
    summary = by_name["drone_embedded_srt.mp4"].telemetry_summary
    assert summary is not None and summary.sample_count == 6
    assert by_name["vertical_rot90.mp4"].rotation == -90
    assert by_name["vertical_rot90.mp4"].is_vertical
    assert by_name["hevc_10bit.mp4"].bit_depth == 10


@pytest.mark.ffmpeg
def test_ingest_records_an_unreadable_file_and_continues(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    (tmp_path / "good.mp4").write_bytes((synthetic_dir / "static.mp4").read_bytes())
    (tmp_path / "broken.mp4").write_text("not a video", encoding="utf-8")
    config = AutocutConfig()
    config.analysis.workers = 1

    files = ingest([tmp_path], config)
    by_name = {f.path.name: f for f in files}
    assert set(by_name) == {"good.mp4", "broken.mp4"}
    assert by_name["good.mp4"].error is None
    assert by_name["broken.mp4"].error


def test_ingest_of_an_empty_folder_returns_nothing(tmp_path: Path) -> None:
    assert ingest([tmp_path], AutocutConfig()) == []


@pytest.mark.ffmpeg
def test_one_worker_failing_does_not_stop_the_others(
    synthetic_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (tmp_path / name).write_bytes((synthetic_dir / "static.mp4").read_bytes())
    config = AutocutConfig()
    config.analysis.workers = 1

    import autocut.core.ingest as ingest_module

    real_ingest_file = ingest_module.ingest_file

    def flaky(scanned: object, cfg: object) -> object:
        if scanned.path.name == "b.mp4":  # type: ignore[attr-defined]
            raise RuntimeError("boom")
        return real_ingest_file(scanned, cfg)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest_module, "ingest_file", flaky)
    files = ingest([tmp_path], config)

    by_name = {f.path.name: f for f in files}
    assert set(by_name) == {"a.mp4", "b.mp4", "c.mp4"}
    assert by_name["b.mp4"].error is not None
    assert by_name["b.mp4"].error.startswith("worker failed:")
    assert by_name["a.mp4"].error is None
    assert by_name["c.mp4"].error is None


def test_module_is_importable_under_spawn() -> None:
    """Pool workers must be picklable module level callables (macOS uses spawn)."""
    from autocut.core.ingest import ingest_file

    assert ingest_file.__module__ == "autocut.core.ingest"
    assert getattr(sys.modules[ingest_file.__module__], "ingest_file", None) is ingest_file

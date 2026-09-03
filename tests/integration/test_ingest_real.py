"""Ingest over the real Sardinia footage. Skips unless AUTOCUT_REAL_FOOTAGE is set.

Synthetic fixtures verify mechanics only (ADR 8); classification has to be checked
against the actual gear before anything is built on top of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.ingest import ingest, scan

pytestmark = [pytest.mark.real_footage, pytest.mark.ffmpeg]


@pytest.fixture(scope="module")
def ingested(real_footage_dir: Path) -> list:  # type: ignore[type-arg]
    config = AutocutConfig()
    return ingest([real_footage_dir], config)


def test_scan_ignores_proxies_and_stills(real_footage_dir: Path) -> None:
    scanned = scan([real_footage_dir])
    suffixes = {item.path.suffix.lower() for item in scanned}
    assert suffixes == {".mp4"}
    assert scanned, "no video files under AUTOCUT_REAL_FOOTAGE"


def test_every_file_probes_cleanly(ingested: list) -> None:  # type: ignore[type-arg]
    failed = [f.path.name for f in ingested if f.error]
    assert failed == []


def test_dji_mini2_files_are_drones_with_embedded_telemetry(ingested: list) -> None:  # type: ignore[type-arg]
    mini2 = [f for f in ingested if f.path.name.startswith("DJI_0")]
    assert mini2, "no DJI Mini 2 files found"
    for source in mini2:
        assert source.source_class == "drone", source.path.name
        assert source.telemetry == "dji_embedded_srt", source.path.name
        assert source.class_signal == "telemetry"
        assert source.telemetry_summary is not None
        assert source.telemetry_summary.sample_count > 0
        assert source.telemetry_summary.max_height_m is not None


def test_action4_files_are_actioncams_with_an_lrf_proxy(ingested: list) -> None:  # type: ignore[type-arg]
    action = [f for f in ingested if f.path.stem.endswith("_D")]
    assert action, "no Osmo Action 4 files found"
    for source in action:
        assert source.source_class == "actioncam", source.path.name
        assert source.class_signal == "make_tag"
        assert source.proxy_path is not None, source.path.name
        assert source.proxy_path.suffix.lower() == ".lrf"
        assert source.codec == "hevc", source.path.name
        # Some clips carry an mjpeg thumbnail as a second video stream; the real
        # picture stream must win, so the recorded size is never the thumbnail's.
        assert (source.width, source.height) == (1920, 1080), source.path.name
    # The Action 4 shoots 10-bit by default, but the set holds one 8-bit clip, so
    # bit depth is observed rather than assumed.
    assert {s.bit_depth for s in action} <= {8, 10}
    assert any(s.bit_depth == 10 for s in action)


def test_xiaomi_files_are_phones(ingested: list) -> None:  # type: ignore[type-arg]
    phones = [f for f in ingested if f.path.name.startswith("VID_")]
    assert phones, "no Xiaomi files found"
    for source in phones:
        assert source.source_class == "phone", source.path.name
        assert source.make == "Xiaomi"
        assert source.gps is not None


def test_files_are_ordered_chronologically(ingested: list) -> None:  # type: ignore[type-arg]
    times = [f.creation_time for f in ingested if f.creation_time is not None]
    assert times == sorted(times)


def test_cache_keys_are_unique(ingested: list) -> None:  # type: ignore[type-arg]
    assert len({f.id for f in ingested}) == len(ingested)

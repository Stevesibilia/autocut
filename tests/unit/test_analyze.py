"""End to end analysis over the synthetic fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.analyze import AnalysisCancelled, analyze_files, choose_hwaccel
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressEvent
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest

pytestmark = pytest.mark.ffmpeg


def project(tmp_path: Path, sources: list[Path]) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(created_at=now, updated_at=now, sources=sources, output_dir=tmp_path / "edit")


def analyzed(
    synthetic_dir: Path, tmp_path: Path, config: AutocutConfig
) -> tuple[Manifest, list[ProgressEvent]]:
    config.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, [synthetic_dir])
    manifest.files = {source.id: source for source in ingest([synthetic_dir], config)}
    events: list[ProgressEvent] = []
    analyze_files(manifest, config, events.append)
    return manifest, events


def test_every_file_gets_at_least_one_scored_segment(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 2
    manifest, events = analyzed(synthetic_dir, tmp_path, settings)

    assert manifest.segments
    file_ids = {segment.file_id for segment in manifest.segments.values()}
    assert file_ids == set(manifest.files)
    for segment in manifest.segments.values():
        assert segment.score is not None
        assert 0.0 <= segment.score <= 1.0
        assert segment.metrics is not None
        assert segment.trimmed_start_s is not None
        assert segment.analyzed_from == "original"
    assert len(events) == len(manifest.files)
    assert all(event.stage == "analyze" for event in events)


def test_static_fixture_is_rejected_for_no_motion(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 1
    manifest, _ = analyzed(synthetic_dir, tmp_path, settings)
    static_id = _file_id(manifest, "static.mp4")
    reasons = {s.reason for s in manifest.segments.values() if s.file_id == static_id}
    assert "no_motion" in reasons


def test_blurred_scores_below_sharp(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 2
    manifest, _ = analyzed(synthetic_dir, tmp_path, settings)
    blurred = _best_score(manifest, "blurred.mp4")
    sharp = _best_score(manifest, "sharp_pan.mp4")
    assert blurred < sharp


def test_drone_takeoff_is_split_out_and_rejected(synthetic_dir: Path, tmp_path: Path) -> None:
    """One continuous shot, heights 0.5, 1.0, 3.0, 25, 30, 2.0, threshold 5.

    The clip never cuts, so shot detection sees a single span. The altitude split
    turns it into three: the takeoff, the cruise, and the descent at the end.
    """
    settings = AutocutConfig()
    settings.analysis.workers = 1
    manifest, _ = analyzed(synthetic_dir, tmp_path, settings)
    drone_id = _file_id(manifest, "drone_embedded_srt.mp4")
    assert manifest.files[drone_id].telemetry == "dji_embedded_srt"

    segments = sorted(
        (s for s in manifest.segments.values() if s.file_id == drone_id),
        key=lambda s: s.start_s,
    )
    assert [(s.start_s, s.end_s) for s in segments] == [(0.0, 3.0), (3.0, 5.0), (5.0, 6.0)]
    assert all(s.split_reason == "altitude" for s in segments)

    takeoff, cruise, descent = segments
    assert takeoff.outcome == "rejected"
    assert takeoff.reason == "low_altitude"
    assert cruise.outcome == "candidate"
    assert cruise.reason is None

    # The boundary sample at t = 3.0 belongs to the cruise, not to the takeoff it was
    # split away from, so the aggregate must not carry the takeoff height across.
    assert takeoff.metrics is not None
    assert cruise.metrics is not None
    # The takeoff span is 0.0 to 3.0 but the drone head trim starts it at 1.0, so its
    # lowest measured height is the sample at t = 1.0 rather than the one at t = 0.0.
    assert takeoff.metrics.min_height_m == pytest.approx(1.0)
    assert cruise.metrics.min_height_m == pytest.approx(25.0)
    # The drone tail trim of 1.0 s ends the usable part of the file at 5.0 s, so the
    # descent span is emptied by the trim and the length rule fires before altitude.
    assert descent.outcome == "rejected"
    assert descent.reason == "too_short"


def test_thumbnails_are_written(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 2
    manifest, _ = analyzed(synthetic_dir, tmp_path, settings)
    for segment in manifest.segments.values():
        assert segment.thumbnail is not None
        assert segment.thumbnail.exists()
        assert segment.thumbnail.parent.name == "thumbs"
        assert segment.sprite is None


def test_sprites_when_enabled(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 1
    settings.analysis.sprites = True
    manifest, _ = analyzed(synthetic_dir, tmp_path, settings)
    sprites = [s.sprite for s in manifest.segments.values() if s.sprite is not None]
    assert sprites
    assert all(path.exists() for path in sprites)


def test_second_run_comes_from_the_cache(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 2
    settings.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, [synthetic_dir])
    manifest.files = {source.id: source for source in ingest([synthetic_dir], settings)}

    first: list[ProgressEvent] = []
    analyze_files(manifest, settings, first.append)
    assert not any(event.extra.get("cached") for event in first)

    second: list[ProgressEvent] = []
    analyze_files(manifest, settings, second.append)
    assert all(event.extra.get("cached") for event in second)


def test_changing_weights_rescores_without_decoding(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 2
    settings.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, [synthetic_dir])
    manifest.files = {source.id: source for source in ingest([synthetic_dir], settings)}
    analyze_files(manifest, settings)
    before = {sid: s.score for sid, s in manifest.segments.items()}

    settings.weights.colorfulness = 8.0
    settings.weights.sharpness = 0.0
    events: list[ProgressEvent] = []
    analyze_files(manifest, settings, events.append)
    after = {sid: s.score for sid, s in manifest.segments.items()}

    assert all(event.extra.get("cached") for event in events)
    assert before != after


def test_cancellation_stops_between_files(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 1
    settings.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, [synthetic_dir])
    manifest.files = {source.id: source for source in ingest([synthetic_dir], settings)}
    assert len(manifest.files) > 2

    seen = 0

    def cancel_after_two(event: ProgressEvent) -> None:
        nonlocal seen
        seen += 1
        if seen >= 2:
            raise AnalysisCancelled

    with pytest.raises(AnalysisCancelled):
        analyze_files(manifest, settings, cancel_after_two)

    assert seen == 2
    analyzed_files = {segment.file_id for segment in manifest.segments.values()}
    assert len(analyzed_files) == 2


def test_a_manifest_without_files_is_a_no_op(tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, [])
    analyze_files(manifest, settings)
    assert manifest.segments == {}


def _file_id(manifest: Manifest, name: str) -> str:
    for file_id, source in manifest.files.items():
        if source.path.name == name:
            return file_id
    raise AssertionError(f"{name} not in the manifest")


def _best_score(manifest: Manifest, name: str) -> float:
    file_id = _file_id(manifest, name)
    scores = [
        s.score for s in manifest.segments.values() if s.file_id == file_id and s.score is not None
    ]
    assert scores
    return max(scores)


def test_the_decoder_is_chosen_once_and_verified(
    synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One probe and one verification for the whole run, not one per file."""
    from autocut.core import analyze as analyze_module
    from autocut.core.hwaccel import Hwaccel

    verifications: list[Path] = []
    monkeypatch.setattr(
        analyze_module, "select_hwaccel", lambda setting: Hwaccel(method="vaapi", device="/dev/x")
    )

    def fake_verify(hwaccel: Hwaccel, path: Path, timeout_s: float = 20.0) -> tuple[bool, str]:
        verifications.append(path)
        return True, ""

    monkeypatch.setattr(analyze_module, "verify_hwaccel", fake_verify)

    config = AutocutConfig()
    files = list(ingest([synthetic_dir], config))
    chosen, warnings = choose_hwaccel(config, files)

    assert chosen.method == "vaapi"
    assert warnings == []
    assert len(verifications) == 1


def test_a_failed_verification_demotes_the_whole_run_once(
    synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One warning for the run, not one per file, and no hardware attempt after it."""
    from autocut.core import analyze as analyze_module
    from autocut.core.hwaccel import Hwaccel

    monkeypatch.setattr(
        analyze_module, "select_hwaccel", lambda setting: Hwaccel(method="vaapi", device="/dev/x")
    )
    monkeypatch.setattr(
        analyze_module,
        "verify_hwaccel",
        lambda hwaccel, path, timeout_s=20.0: (False, "Cannot load libcuda.so.1"),
    )

    config = AutocutConfig()
    files = list(ingest([synthetic_dir], config))
    chosen, warnings = choose_hwaccel(config, files)

    assert chosen.method == "none"
    assert len(warnings) == 1
    assert "Cannot load libcuda.so.1" in warnings[0]


def test_a_run_warning_never_reaches_the_progress_channel(
    synthetic_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One event per file, whatever the decoder did: a front end may cancel from it."""
    from autocut.core import analyze as analyze_module
    from autocut.core.hwaccel import Hwaccel

    monkeypatch.setattr(
        analyze_module, "select_hwaccel", lambda setting: Hwaccel(method="vaapi", device="/dev/x")
    )
    monkeypatch.setattr(
        analyze_module,
        "verify_hwaccel",
        lambda hwaccel, path, timeout_s=20.0: (False, "no device"),
    )

    settings = AutocutConfig()
    settings.analysis.workers = 1
    settings.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, [synthetic_dir])
    manifest.files = {source.id: source for source in ingest([synthetic_dir], settings)}

    events: list[ProgressEvent] = []
    analyze_files(manifest, settings, events.append)

    assert len(events) == len(manifest.files)
    assert manifest.analysis.hwaccel == "none"
    assert len(manifest.analysis.warnings) == 1
    assert "no device" in manifest.analysis.warnings[0]


def test_software_configuration_skips_verification(
    synthetic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autocut.core import analyze as analyze_module

    def explode(*args: object, **kwargs: object) -> tuple[bool, str]:
        raise AssertionError("software decoding must not be verified")

    monkeypatch.setattr(analyze_module, "verify_hwaccel", explode)

    config = AutocutConfig()
    config.analysis.hwaccel = "off"
    chosen, warnings = choose_hwaccel(config, list(ingest([synthetic_dir], config)))
    assert chosen.method == "none"
    assert warnings == []


def test_verification_uses_the_proxy_when_analysis_will(
    synthetic_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifying the original would prove nothing about decoding the proxy."""
    from autocut.core import analyze as analyze_module
    from autocut.core.hwaccel import Hwaccel

    video = tmp_path / "DJI_0001_D.MP4"
    video.write_bytes((synthetic_dir / "sharp_pan.mp4").read_bytes())
    proxy = tmp_path / "DJI_0001_D.LRF"
    proxy.write_bytes((synthetic_dir / "static.mp4").read_bytes())

    seen: list[Path] = []
    monkeypatch.setattr(
        analyze_module, "select_hwaccel", lambda setting: Hwaccel(method="vaapi", device="/dev/x")
    )
    monkeypatch.setattr(
        analyze_module,
        "verify_hwaccel",
        lambda hwaccel, path, timeout_s=20.0: (seen.append(path), (True, ""))[1],
    )

    config = AutocutConfig()
    choose_hwaccel(config, list(ingest([tmp_path], config)))
    assert seen == [proxy]

    seen.clear()
    config.analysis.use_proxies = False
    choose_hwaccel(config, list(ingest([tmp_path], config)))
    assert seen == [video]


def test_the_run_records_the_decoder_it_used(synthetic_dir: Path, tmp_path: Path) -> None:
    """Recorded on the manifest so timings are comparable between machines."""
    settings = AutocutConfig()
    settings.analysis.workers = 1
    settings.analysis.hwaccel = "off"
    manifest, _ = analyzed(synthetic_dir, tmp_path, settings)
    assert manifest.analysis.hwaccel == "none"
    assert manifest.analysis.files_analyzed == len(manifest.files)
    assert manifest.analysis.files_from_cache == 0
    assert manifest.analysis.completed


def test_a_cancelled_run_is_recorded_as_incomplete(synthetic_dir: Path, tmp_path: Path) -> None:
    settings = AutocutConfig()
    settings.analysis.workers = 1
    settings.analysis.hwaccel = "off"
    settings.cache.dir = tmp_path / "cache"
    manifest = project(tmp_path, [synthetic_dir])
    manifest.files = {source.id: source for source in ingest([synthetic_dir], settings)}

    def cancel_at_once(event: ProgressEvent) -> None:
        raise AnalysisCancelled

    with pytest.raises(AnalysisCancelled):
        analyze_files(manifest, settings, cancel_at_once)
    assert not manifest.analysis.completed

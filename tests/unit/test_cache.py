"""Cache round trip, invalidation and the inspection commands."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core import cache as cache_module
from autocut.core.cache import (
    CacheEntry,
    cache_dir,
    cache_stats,
    entry_path,
    prune,
    read_entry,
    read_entry_cached,
    thumb_index,
    write_entry,
)
from autocut.core.config import AutocutConfig
from autocut.core.manifest import ANALYSIS_SCHEMA_VERSION

runner = CliRunner()


def config_in(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    return config


def sample_entry(key: str = "abc123") -> CacheEntry:
    return CacheEntry(
        file_key=key,
        source="proxy",
        arrays={
            "timestamps": np.arange(4, dtype=np.float64) / 2.0,
            "sharpness": np.array([10.0, 20.0, 30.0, 40.0]),
            "clipping": np.zeros(4),
            "motion": np.array([0.1, 0.1, 0.2, 0.3]),
            "stability": np.ones(4),
            "colorfulness": np.full(4, 0.25),
        },
        shot_bounds=[(0.0, 1.0), (1.0, 2.0)],
        telemetry=[{"time_s": 0.0, "height_m": 12.5}],
        probe={"codec": "h264"},
        thumb_frames=np.zeros((2, 4, 4, 3), dtype=np.uint8),
        warnings=["software decoding"],
    )


def test_default_directory_is_under_the_platform_cache(tmp_path: Path) -> None:
    config = AutocutConfig()
    assert config.cache.dir is None
    directory = cache_dir(config)
    assert directory.name == f"v{ANALYSIS_SCHEMA_VERSION}"
    assert directory.exists()
    # Configuring the directory overrides the platform one.
    assert cache_dir(config_in(tmp_path)).parent == tmp_path / "cache"


def test_round_trip(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    entry = sample_entry()
    write_entry(entry, config)

    loaded = read_entry("abc123", config)
    assert loaded is not None
    assert loaded.source == "proxy"
    assert loaded.shot_bounds == [(0.0, 1.0), (1.0, 2.0)]
    assert loaded.telemetry == [{"time_s": 0.0, "height_m": 12.5}]
    assert loaded.probe == {"codec": "h264"}
    assert loaded.warnings == ["software decoding"]
    assert loaded.frame_count == 4
    for name, values in entry.arrays.items():
        assert np.allclose(loaded.arrays[name], values)
    assert loaded.thumb_frames is not None
    assert loaded.thumb_frames.shape == (2, 4, 4, 3)


def test_a_missing_entry_reads_as_none(tmp_path: Path) -> None:
    assert read_entry("nothing", config_in(tmp_path)) is None


def test_changing_the_sample_rate_misses(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    assert read_entry("abc123", config) is not None

    config.analysis.sample_fps = 4.0
    assert read_entry("abc123", config) is None


def test_changing_the_long_side_misses(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    config.analysis.sample_long_side = 480
    assert read_entry("abc123", config) is None


def test_a_stale_schema_version_misses(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    meta = entry_path("abc123", config).with_suffix(".json")
    meta.write_text(
        meta.read_text(encoding="utf-8").replace(
            f'"analysis_schema_version": {ANALYSIS_SCHEMA_VERSION}',
            '"analysis_schema_version": 99',
        ),
        encoding="utf-8",
    )
    assert read_entry("abc123", config) is None


def test_no_temporary_files_are_left_behind(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    assert list(cache_dir(config).glob("*.tmp")) == []


def test_sprites_survive_the_round_trip(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    entry = sample_entry()
    entry.sprites = [
        np.zeros((4, 16, 3), dtype=np.uint8),
        np.zeros((4, 8, 3), dtype=np.uint8),
    ]
    write_entry(entry, config)
    loaded = read_entry("abc123", config)
    assert loaded is not None
    assert [sprite.shape for sprite in loaded.sprites] == [(4, 16, 3), (4, 8, 3)]


def test_embeddings_survive_the_round_trip(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    entry = sample_entry()
    entry.embeddings = np.array([[0.6, 0.8], [0.0, 1.0]], dtype=np.float32)
    entry.embedding_model = config.providers.embedding_model
    write_entry(entry, config)

    loaded = read_entry("abc123", config)
    assert loaded is not None
    assert loaded.embedding_model == config.providers.embedding_model
    assert loaded.embeddings is not None
    assert np.allclose(loaded.embeddings, entry.embeddings)


def test_another_model_drops_the_vectors_and_keeps_the_metrics(tmp_path: Path) -> None:
    """A model change costs one forward pass per shot, never a decode."""
    config = config_in(tmp_path)
    entry = sample_entry()
    entry.embeddings = np.array([[0.6, 0.8], [0.0, 1.0]], dtype=np.float32)
    entry.embedding_model = config.providers.embedding_model
    write_entry(entry, config)

    config.providers.embedding_model = "ViT-L-14/laion2b_s32b_b82k"
    loaded = read_entry("abc123", config)
    assert loaded is not None
    assert loaded.embeddings is None
    assert loaded.embedding_model is None
    assert np.allclose(loaded.arrays["sharpness"], entry.arrays["sharpness"])
    assert loaded.thumb_frames is not None
    assert loaded.thumb_frames.shape == (2, 4, 4, 3)


def test_an_entry_without_embeddings_reads_as_having_none(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    loaded = read_entry("abc123", config)
    assert loaded is not None
    assert loaded.embeddings is None
    assert loaded.embedding_model is None


def test_the_thumbnail_index_of_a_segment() -> None:
    # Two segments split out of one shot both describe the frame that was cached.
    assert thumb_index("aaa:0", 3) == 0
    assert thumb_index("aaa:2", 3) == 2
    assert thumb_index("aaa:7", 3) == 2
    assert thumb_index("aaa:0", 0) == -1
    assert thumb_index("no-colon", 3) == 0
    assert thumb_index("aaa:not-a-number", 3) == 0


def test_stats_and_prune(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry("old"), config)
    write_entry(sample_entry("new"), config)

    stats = cache_stats(config)
    assert stats.entries == 2
    assert stats.megabytes > 0

    old = entry_path("old", config)
    stale = time.time() - 40 * 86400
    os.utime(old, (stale, stale))
    assert prune(config, older_than_days=30) == 1
    assert read_entry("old", config) is None
    assert read_entry("new", config) is not None


def test_cache_command_reports_the_directory(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    toml.write_text(f'[cache]\ndir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    write_entry(sample_entry(), config_in(tmp_path))

    result = runner.invoke(app, ["cache", "--config", str(toml)])
    assert result.exit_code == 0, result.stdout
    assert "Entries:" in result.stdout
    assert "1" in result.stdout


def test_cache_prune_command(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    toml.write_text(f'[cache]\ndir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    config = config_in(tmp_path)
    write_entry(sample_entry("old"), config)
    stale = time.time() - 100 * 86400
    os.utime(entry_path("old", config), (stale, stale))

    result = runner.invoke(app, ["cache", "prune", "--config", str(toml), "--older-than", "30"])
    assert result.exit_code == 0, result.stdout
    assert "Removed" in result.stdout
    assert read_entry("old", config) is None


@pytest.mark.parametrize("command", [["cache", "--help"], ["cache", "prune", "--help"]])
def test_cache_help(command: list[str]) -> None:
    result = runner.invoke(app, command)
    assert result.exit_code == 0


# --- hardening (decision 5, issue #78) ---------------------------------------


def test_a_truncated_arrays_file_reads_as_none(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    arrays_path = entry_path("abc123", config)
    data = arrays_path.read_bytes()
    arrays_path.write_bytes(data[: len(data) // 2])

    assert read_entry("abc123", config) is None


def test_mismatched_write_tokens_read_as_none(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    meta_path = entry_path("abc123", config).with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["write_token"] = "not-the-same-token"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert read_entry("abc123", config) is None


def test_a_token_present_in_only_one_file_reads_as_none(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    meta_path = entry_path("abc123", config).with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["write_token"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert read_entry("abc123", config) is None


def test_an_entry_with_no_token_in_either_file_still_reads(tmp_path: Path) -> None:
    """Entries written before write tokens existed must stay valid."""
    config = config_in(tmp_path)
    entry = sample_entry()
    write_entry(entry, config)
    arrays_path = entry_path("abc123", config)
    meta_path = arrays_path.with_suffix(".json")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["write_token"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with np.load(arrays_path) as payload:
        arrays = {name: payload[name] for name in payload.files if name != "write_token"}
    np.savez_compressed(arrays_path, **arrays)  # type: ignore[arg-type]

    loaded = read_entry("abc123", config)
    assert loaded is not None
    assert loaded.shot_bounds == entry.shot_bounds


def test_a_mismatched_file_key_reads_as_none(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    meta_path = entry_path("abc123", config).with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["file_key"] = "someone-elses-key"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert read_entry("abc123", config) is None


def test_prune_removes_orphaned_metadata_and_temp_files(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry("new"), config)
    directory = cache_dir(config)

    orphan_json = directory / "orphan_2-0_320.json"
    orphan_json.write_text("{}", encoding="utf-8")
    orphan_tmp = directory / "orphan_2-0_320.12345.npz.tmp"
    orphan_tmp.write_bytes(b"partial")
    stale = time.time() - 40 * 86400
    os.utime(orphan_json, (stale, stale))
    os.utime(orphan_tmp, (stale, stale))

    assert prune(config, older_than_days=30) == 0
    assert not orphan_json.exists()
    assert not orphan_tmp.exists()
    assert read_entry("new", config) is not None


def test_prune_count_is_only_npz_entries(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry("old"), config)
    directory = cache_dir(config)
    old_json = entry_path("old", config).with_suffix(".json")
    stale = time.time() - 40 * 86400
    os.utime(entry_path("old", config), (stale, stale))
    os.utime(old_json, (stale, stale))

    extra_tmp = directory / "leftover.99999.json.tmp"
    extra_tmp.write_text("{}", encoding="utf-8")
    os.utime(extra_tmp, (stale, stale))

    assert prune(config, older_than_days=30) == 1
    assert not extra_tmp.exists()


def test_a_write_then_read_round_trips_with_no_tmp_left(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    entry = sample_entry()
    write_entry(entry, config)

    loaded = read_entry("abc123", config)
    assert loaded is not None
    assert loaded.shot_bounds == entry.shot_bounds
    assert list(cache_dir(config).glob("*.tmp")) == []


# --- the in-memory LRU (design decision 5, issue #82) ------------------------


def counting_read_entry(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Count calls to the real ``read_entry`` that ``read_entry_cached`` falls through to."""
    calls: list[str] = []
    real_read_entry = cache_module.read_entry

    def counting(file_key: str, config: AutocutConfig, sprites: bool = True) -> CacheEntry | None:
        calls.append(file_key)
        return real_read_entry(file_key, config, sprites=sprites)

    monkeypatch.setattr(cache_module, "read_entry", counting)
    return calls


def test_a_cache_hit_reads_from_disk_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    calls = counting_read_entry(monkeypatch)

    for _ in range(5):
        loaded = read_entry_cached("abc123", config)
        assert loaded is not None

    assert calls == ["abc123"]


def test_rewriting_an_entry_is_read_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = config_in(tmp_path)
    write_entry(sample_entry(), config)
    calls = counting_read_entry(monkeypatch)

    assert read_entry_cached("abc123", config) is not None
    write_entry(sample_entry(), config)
    assert read_entry_cached("abc123", config) is not None

    assert calls == ["abc123", "abc123"]


def test_memory_entries_zero_disables_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    config.cache.memory_entries = 0
    write_entry(sample_entry(), config)
    calls = counting_read_entry(monkeypatch)

    for _ in range(3):
        assert read_entry_cached("abc123", config) is not None

    assert calls == ["abc123", "abc123", "abc123"]


def test_the_cache_holds_at_most_memory_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    config.cache.memory_entries = 2
    for key in ("a", "b", "c"):
        write_entry(sample_entry(key), config)
    calls = counting_read_entry(monkeypatch)

    read_entry_cached("a", config)
    read_entry_cached("b", config)
    read_entry_cached("c", config)  # evicts "a", the least recently used
    calls.clear()

    assert read_entry_cached("a", config) is not None  # missed, reads again
    assert calls == ["a"]
    calls.clear()
    assert read_entry_cached("c", config) is not None  # still cached
    assert calls == []


def test_a_missing_file_reads_as_none_and_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    calls = counting_read_entry(monkeypatch)
    assert read_entry_cached("nothing", config) is None
    assert calls == []


def test_a_cached_array_cannot_be_written(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    entry = sample_entry()
    write_entry(entry, config)

    loaded = read_entry_cached("abc123", config)
    assert loaded is not None
    assert loaded.thumb_frames is not None
    with pytest.raises(ValueError, match="read-only"):
        loaded.arrays["sharpness"][0] = 999.0
    with pytest.raises(ValueError, match="read-only"):
        loaded.thumb_frames[0, 0, 0, 0] = 1

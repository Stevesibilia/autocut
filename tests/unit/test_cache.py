"""Cache round trip, invalidation and the inspection commands."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core.cache import (
    CacheEntry,
    cache_dir,
    cache_stats,
    entry_path,
    prune,
    read_entry,
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

"""Cache key stability: same content and stat means same key, wherever the file lives."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from autocut.core.cachekey import cache_key


def write(path: Path, payload: bytes, mtime_ns: int = 1_700_000_000_000_000_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def test_key_is_32_hex_characters(tmp_path: Path) -> None:
    key = cache_key(write(tmp_path / "a.mp4", b"x" * 4096))
    assert len(key) == 32
    assert all(character in "0123456789abcdef" for character in key)


def test_copy_at_another_path_keeps_the_key(tmp_path: Path) -> None:
    original = write(tmp_path / "src" / "DJI_0001.MP4", os.urandom(3 * 1024 * 1024))
    copied = tmp_path / "dst" / "DJI_0001.MP4"
    copied.parent.mkdir(parents=True)
    shutil.copy2(original, copied)
    assert cache_key(original) == cache_key(copied)


def test_different_first_megabyte_gives_a_different_key(tmp_path: Path) -> None:
    size = 3 * 1024 * 1024
    tail = os.urandom(size // 2)
    first = write(tmp_path / "a.mp4", b"\x00" * (size - len(tail)) + tail)
    second = write(tmp_path / "b.mp4", b"\x01" * (size - len(tail)) + tail)
    assert first.stat().st_size == second.stat().st_size
    assert first.stat().st_mtime_ns == second.stat().st_mtime_ns
    assert cache_key(first) != cache_key(second)


def test_different_last_megabyte_gives_a_different_key(tmp_path: Path) -> None:
    size = 3 * 1024 * 1024
    head = os.urandom(size // 2)
    first = write(tmp_path / "a.mp4", head + b"\x00" * (size - len(head)))
    second = write(tmp_path / "b.mp4", head + b"\x01" * (size - len(head)))
    assert cache_key(first) != cache_key(second)


def test_touching_a_file_changes_the_key(tmp_path: Path) -> None:
    path = write(tmp_path / "a.mp4", b"x" * 4096)
    before = cache_key(path)
    os.utime(path, ns=(1_800_000_000_000_000_000, 1_800_000_000_000_000_000))
    assert cache_key(path) != before


def test_missing_file_yields_an_empty_key(tmp_path: Path) -> None:
    assert cache_key(tmp_path / "nope.mp4") == ""

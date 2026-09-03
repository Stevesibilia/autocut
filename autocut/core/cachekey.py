"""Cache key for a source file (ADR 6).

Hashing a whole 4K file costs as much as analyzing it, so the key is size,
modification time and the first and last megabyte of content. The path is
deliberately excluded: footage moves between the Linux box and the MacBook and a
copy must keep its cache entry.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_BYTES = 1 << 20
DIGEST_BYTES = 16  # 32 hex characters.


def cache_key(path: Path, *, chunk_bytes: int = CHUNK_BYTES) -> str:
    """Stable 32 character key for ``path``, or an empty string when it cannot be read."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    digest = hashlib.blake2b(digest_size=DIGEST_BYTES)
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}:".encode())
    try:
        with path.open("rb") as handle:
            digest.update(handle.read(chunk_bytes))
            if stat.st_size > chunk_bytes:
                handle.seek(max(stat.st_size - chunk_bytes, chunk_bytes))
                digest.update(handle.read(chunk_bytes))
    except OSError:
        return ""
    return digest.hexdigest()

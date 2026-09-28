## Why

Two findings from the 2026-09-22 project review, triaged on 2026-09-27.

- **#72.** `release.yml` runs on every `v*` tag and calls `make dmg`, which is a placeholder that exits 1 until M6. Every tag produces a failed run.
- **#71.** The docstring of `autocut/core/cachekey.py` says a copy must keep its cache entry, and SPEC §9 says the key includes the path. Neither matches the code: the key is size, mtime and the first and last MiB, without the path. A copy keeps its entry only when the copy preserves the mtime. ADR 6 accepts that limit on purpose. The key doubles as each file's id in the manifest, so changing it would re-analyze every cached file and give existing projects new file and segment ids. The user chose to document the limit rather than change the key.

## What Changes

- `release.yml` runs only on manual dispatch until M6 gives `make dmg` a real bundle. Pipeline only, no behaviour to specify.
- The cache key requirement gains a scenario for a copy that does not preserve the mtime. The docstring and SPEC §9 say which copies keep their entry. The key itself does not change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `footage-ingest`: the cache key requirement states what happens to a copy that loses its mtime.

## Impact

`.github/workflows/release.yml`, `autocut/core/cachekey.py` (docstring only), `SPEC.md` §9, `tests/unit/test_cachekey.py`. No code path changes.

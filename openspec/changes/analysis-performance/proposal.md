## Why

Issue #82, from the 2026-09-28 project review. Analysis probes every file twice. Ingest and export wait on subprocesses from spawn process pools, which re-import numpy and cv2 in every worker. One hour of footage peaks near 20 GB of memory in a single analysis worker, because every sampled frame is stacked again as float64 in two places. The GUI re-reads every cache entry from disk and recomputes the visual hashes on every slider move.

## What Changes

- Analysis SHALL reuse the probe result ingest recorded instead of running ffprobe again.
- Ingest and export SHALL run their subprocess-bound workers on threads.
- Sampling SHALL decode frames straight into one array, and motion and content differences SHALL be computed pairwise, so analysis holds one copy of the sampled frames. The measured values SHALL not change beyond floating-point reduction order.
- Selection SHALL keep recently read cache entries in memory, read-only, and SHALL memoise the visual hashes derived from them. A new `cache.memory_entries` setting sizes the cache.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frame-analysis`: probe reuse and bounded memory.
- `clip-selection`: in-memory entry cache for re-selection.

## Impact

`autocut/core/probe.py`, `analyze.py`, `ingest.py`, `export.py`, `sampler.py`, `metrics.py`, `segment.py`, `cache.py`, `select.py`, `config.py` (`CacheConfig.memory_entries`), `autocut.example.toml`, tests in `tests/unit/`, `SPEC.md` §12, `CHANGELOG.md`. No schema change.

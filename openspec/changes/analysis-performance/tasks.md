## 0. Baseline, no commit

- [x] 0.1 On `origin/main`, in a temp worktree or a clean checkout, take measurements (a), (b) and (c) from design decision 6, and keep the numbers.

## 1. Probe reuse and thread pools (design decisions 1 and 2), one commit

- [x] 1.1 `probe_from_source` and its use in `analyze_file`; the `ThreadPoolExecutor`s in `ingest` and `export._run`; `functools.cache` on `physical_cores`.
- [x] 1.2 Tests:
  - `probe_from_source` round-trips every field listed in decision 1;
  - `analyze_file` on a synthetic fixture with `autocut.core.analyze.probe_file` monkeypatched to raise still succeeds;
  - `ingest` and `export` with `workers=2` still isolate a failing worker, as in #78's tests. They now run on threads, so a monkeypatched worker is visible: add one monkeypatch-based pool test per module.
- [x] 1.3 Commit: `perf(core): reuse the ingest probe and run subprocess work on threads`.

## 2. Memory (decisions 3 and 4), one commit

- [x] 2.1 `read_frames` into one growing array; `sample_frames` with `expected`; pairwise `motion_series` and `content_series`.
- [x] 2.2 Tests:
  - the seven sampler fakes updated;
  - growth past `expected` (expected=1 with 5 frames) and a stream that ends mid-frame;
  - short reads (a fake stdout whose `readinto` returns half a frame at a time);
  - old against new for `motion_series` and `content_series` as in decision 4.
- [x] 2.3 Commit: `perf(core): hold one copy of the sampled frames during analysis`.

## 3. Selection entry cache (decision 5), one commit

- [x] 3.1 `CacheConfig.memory_entries`, `read_entry_cached`, `CacheEntry.derived`, read-only arrays, the memoised visual features, and `_load_entries` switched over.
- [x] 3.2 Tests in `tests/unit/test_cache.py` and `tests/unit/test_select.py`:
  - ten `select_clips` calls read each entry from disk once (count `np.load` with a monkeypatch) and return identical results;
  - rewriting an entry with `write_entry` makes the next call read it again;
  - `memory_entries = 0` reads every time;
  - the cache holds at most `memory_entries` entries;
  - a cached array cannot be written.
- [x] 3.3 Commit: `perf(core): keep analysis entries in memory across re-selections`.

## 4. Docs (decision 7), one commit

- [x] 4.1 `SPEC.md` §12, `CHANGELOG.md`, `autocut.example.toml`. Format each Markdown file with `sjust format-md <path>`.
- [x] 4.2 Commit: `docs: describe the analysis memory bound and the selection cache`.

## 5. Gates and hand-back

- [ ] 5.1 `make lint` and `openspec validate analysis-performance --strict`.
- [ ] 5.2 Through the test runner: `make test` and `make docker-test-gui`. Quote the counts.
- [ ] 5.3 Measurements (a), (b) and (c) on the branch, next to the baseline from 0.1, in a table in the hand-back.
- [ ] 5.4 Tick these boxes, push the branch and hand back.

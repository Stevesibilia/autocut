## Context

Read on `main` at `a635dd2`, which includes #78's pipeline-robustness:

- `analyze_file` (`autocut/core/analyze.py:65`) runs `probe_file(source.path)` at `:73`, a second ffprobe per file after `ingest_file` already probed it (`autocut/core/ingest.py:137`). Of the probe, analysis reads only `ok`/`error`, `display_width`/`display_height` (so `width`, `height`, `rotation`) through `sample_size` (`sampler.py:56`), `duration_s` (`analyze.py:122`), `fps` on the pyscenedetect path (`:125`), and `subtitle_streams` in the embedded telemetry adapter (`telemetry/dji.py:173`). It stores `probe.model_dump()` as `CacheEntry.probe`, which is written at `cache.py:215` and never read. `SourceFile` (`manifest.py:139-164`) carries every field analysis reads.
- `ingest` and `export._run` use spawn `ProcessPoolExecutor`s (`ingest.py:195`, `export.py:375`). Their workers mostly wait on subprocesses: ffprobe, a subtitle extract, a 2 MB hash read and a directory listing for `ingest_file`, and one ffmpeg run for `export_one`. Each spawn worker re-imports numpy, cv2 and pydantic. `analyze_file` is CPU-heavy (cv2, numpy, zlib) and rightly uses processes. `physical_cores()` (`ingest.py:49`) shells out to `sysctl` on every call.
- Memory in `analyze_file`:
  - `sample_frames` collects frames as a list of `bytes` and then `np.frombuffer(b"".join(raw))` (`sampler.py:216`, `:247`). That is two copies at the peak.
  - `motion_series` (`metrics.py:~88`) stacks every gray frame as float64, which is 8/3 of the RGB size, and then allocates the full diff.
  - `content_series` (`segment.py:48`) stacks every HSV frame as float64, 8x the RGB size, plus the full diff.

  At the defaults (2 fps, 320 px long side) an hour of footage is about 1.24 GB of RGB, so one long file peaks near 20 GB in one worker. Each of these consumers needs only consecutive pairs.

- `select_clips` calls `_load_entries` (`select.py:222`), which calls `read_entry(..., sprites=False)` for every candidate file on every call. `_build_features` (`:314`) recomputes `perceptual_hash` and `color_histogram` from the thumbnail frames each time. The GUI triggers re-selection on every slider move after a 250 ms debounce (`gui/state.py:489-505`). Nothing is memoised.
- No test monkeypatches the pool classes. `tests/unit/test_ingest.py:198-203` asserts that `ingest_file` is picklable at module level. Seven tests monkeypatch `autocut.core.sampler.read_frames` with fakes that return a list of `bytes`.

## Decisions

**1. Analysis reuses the ingest probe.** Add `probe_from_source(source: SourceFile) -> ProbeResult` to `autocut/core/probe.py`. It copies `path`, `error`, `duration_s`, `width`, `height`, `rotation`, `fps`, `codec`, `pix_fmt`, `bit_depth`, `creation_time`, `make`, `model`, `gps`, `subtitle_streams` and `data_streams`, and leaves the rest at their defaults. `analyze_file` uses it instead of `probe_file`. `CacheEntry.probe` then holds this reduced dump. Amended at review: the dump uses `exclude_unset=True`. The real-footage A/B showed the plain dump stored `has_audio: false` for actioncam files that do have audio, a default that read like a measurement. Nobody reads it, so the loss of `color_transfer`, `encoder`, the tag dicts and `has_audio` there is accepted. Telemetry extraction in `_telemetry_payload` stays: ingest keeps only the summary, and the samples are needed. It already runs only for files whose `source.telemetry != "none"`.
Rejected: storing the telemetry series in the manifest. It would bloat the project file for data the cache already holds.

**2. Threads for waiting.** `ingest` and `export._run` use `concurrent.futures.ThreadPoolExecutor` with the same `max_workers` as today, and no `mp_context`. The per-future guards from #78 stay as they are. `ingest_file` and `export_one` remain module-level functions, and the picklability test stays. `physical_cores` is decorated with `functools.cache`. `analyze_files` keeps its spawn process pool.
Risk: `ingest_file`'s blake2b hashing and SRT parsing now share the GIL. hashlib releases the GIL for large buffers, and the SRT parse is small. If the wall time of `autocut analyze` on the fixtures gets worse, report it with the numbers.

**3. Frames go straight into one array.** Change `read_frames` to `read_frames(command: list[str], shape: tuple[int, int, int], expected: int) -> tuple[np.ndarray, int, str]`. It allocates `np.empty((max(expected, 1), h, w, 3), np.uint8)` and reads each frame with `process.stdout.readinto(memoryview(buffer[i]).cast("B"))`. It doubles the capacity with `np.resize`-free growth (allocate twice as much, copy, drop the old one) when `expected` was too small. It returns `buffer[:count]` as a copy only when `count < capacity // 2`; otherwise it returns the view. A short final read (a partial frame) ends the loop, as today. The stderr thread and timeout handling from #78 stay unchanged. `sample_frames` passes `expected = int(probe.duration_s * config.analysis.sample_fps) + 2` and drops the `b"".join`. The single-frame fallback passes `expected=1`. Update the seven fakes in `tests/unit/test_sampler.py` to the new signature and return type.

**4. Pairwise diffs.** Rewrite `motion_series` (`metrics.py`) and `content_series` (`segment.py`) to walk consecutive frames. Each converts the current frame (`to_gray`, or `cv2.cvtColor(..., COLOR_RGB2HSV)`), casts it to float64 as today, takes `np.abs(current - previous).mean() / MAX_LEVEL` (or `/ 255.0`), and keeps only the previous converted frame. The dtype and formula are unchanged. Only the reduction order can differ. Tests compare the new functions with a verbatim copy of the old ones, placed in the test file, on random frames and on the synthetic fixtures' sampled frames. They assert `np.allclose(new, old, rtol=1e-12, atol=0)`. The first-frame conventions stay exactly as they are (motion borrows the second value, content starts at 0).

**5. A read-only entry cache for selection.** In `autocut/core/cache.py`, add `read_entry_cached(file_key: str, config: AutocutConfig) -> CacheEntry | None`, which is `read_entry(..., sprites=False)` behind an in-process LRU:

- The key is `(str(arrays_path), npz.st_mtime_ns, npz.st_size, json.st_mtime_ns, config.providers.embedding_model)`, from one `stat` of each file. A missing file means `None`, and any stale key for that path is dropped.
- The cache is an `OrderedDict` guarded by a `threading.Lock`, because the GUI runs selection both inline and on its worker thread. Its size is `config.cache.memory_entries`, a new `CacheConfig` field: `int = Field(default=256, ge=0, description=...)`. `0` disables the cache.
- On insert, every array in the entry (`arrays` values, `thumb_frames`, `embeddings`) gets `flags.writeable = False`, so a caller that tries to mutate a shared entry fails loudly instead of corrupting the next selection.
- Add `derived: dict[str, Any] = field(default_factory=dict)` to `CacheEntry` for values computed from an entry. `_build_features` in `select.py` memoises `(perceptual_hash, color_histogram)` in `entry.derived` under the key `f"visual:{index}"`, where `index` is the thumbnail index. `derived` is never written to disk.
- `select._load_entries` calls `read_entry_cached`. Nothing else changes caller. `analyze`, `embeddings`, `describe` and `thumbs` keep `read_entry`.
- `write_entry`, `prune` and `clear` need no hook: a rewritten or deleted file changes or removes the stat key.

**6. Measure, before and after.** Numbers go in the hand-back and the PR. Measure on `origin/main` first, then on the branch:

- (a) Peak RSS of one `analyze_file` call on a 10-minute synthetic 1080p clip. Generate it into a temp dir with `ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=30 -t 600 -pix_fmt yuv420p`. Run the call in a fresh Python subprocess that prints `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` at the end, with an isolated `cache.dir`.
- (b) Wall time of `autocut analyze tests/fixtures/synthetic --out <tmp>` with a cold isolated cache.
- (c) Ten consecutive `select_clips` calls on that project: the first call and the median of the other nine.

Put the throwaway measuring script in the hand-back, not in the repository.

**7. Docs.** `SPEC.md` §12 Performance: one paragraph on the probe reuse, the thread pools, the pairwise measurement ("analysis holds one copy of the sampled frames") and the selection cache (`cache.memory_entries`). One `### Changed` line in `CHANGELOG.md` under `## [Unreleased]`. Add `cache.memory_entries` to `autocut.example.toml` with its comment.

## Not touched

- `ffprobe` wrapper consolidation, the tunables, the module splits: issue #81, next.
- The analysis process pool and its worker count.
- The on-disk cache format and `ANALYSIS_SCHEMA_VERSION`. `derived` is memory only.
- Thumbnails and sprites. They still index the full frame array after shot detection, which is why the frames stay in memory at all.

## Risks / Trade-offs

- **A metric changes beyond `rtol=1e-12`.** Stop and report the values. Do not loosen the tolerance. The architect re-runs the real-footage A/B before merge in any case.
- **A caller mutates an entry from the cache.** The read-only flags make it raise `ValueError: assignment destination is read-only`. Fix the caller by copying if the mutation is local and legitimate, and list it in the hand-back. Do not drop the flag.
- **Threads in ingest break a test** that relied on process isolation (a monkeypatch that now also reaches the workers, for example). Report it.
- **`readinto` on a pipe returns fewer bytes than a frame mid-stream.** Pipes can return short reads. Loop until the frame is full or EOF. Only an EOF with a partial frame ends the loop.

## Migration Plan

None.

## Open Questions

None.

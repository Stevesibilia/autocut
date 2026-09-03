## 1. Sampler

- [x] 1.1 Add `autocut/core/sampler.py` with `build_sample_command(path, fps, long_side, hwaccel) -> list[str]` and `sample_frames(path, probe, config) -> SampledFrames` (timestamps array, frames array `N x H x W x 3 uint8`, source proxy or original). Verify command construction with a unit test on the argument list and frame count with an `ffmpeg` marked test on `sharp_pan.mp4` (about 12 frames for 6 s at 2 fps).
- [x] 1.2 Implement the software fallback when the hardware attempt fails. Verify with a unit test that fakes a failing first subprocess and asserts the second call has no `-hwaccel`.
- [x] 1.3 Read from the proxy when attached and enabled. Verify with a unit test asserting the command targets the proxy path.

## 2. Metrics

- [x] 2.1 Add `autocut/core/metrics.py` with pure functions `sharpness`, `clipping_fraction`, `motion_series`, `stability_series`, `colorfulness` and `frame_metrics(frames, source_class) -> FrameMetrics`. Verify with unit tests on synthetic NumPy images: blurred lower sharpness than sharp, white frame clipping near 1, identical frames motion 0, alternating frames high motion and low stability, gray frame colorfulness near 0.
- [x] 2.2 Implement the center crop for `actioncam` sharpness. Verify with a test where edge noise raises full-frame sharpness but not center-crop sharpness.

## 3. Segmentation and rules

- [x] 3.1 Add `autocut/core/segment.py` with `detect_shots(frames, timestamps, threshold, min_len) -> list[tuple[float, float]]` and `apply_trims(bounds, duration, source_class, config)`. Verify with an `ffmpeg` marked test on `multishot.mp4` asserting three segments with boundaries within 0.5 s of 3.0 and 6.0, and a unit test for the phone trim scenario.
- [x] 3.2 Add `autocut/core/rules.py` with `apply_rules(segment, metrics, telemetry, config) -> str | None` implementing `too_short`, `low_altitude`, `no_motion`, `shaky`, `clipped` in that order. Verify with unit tests for every scenario in `specs/rejection-rules/spec.md`.
- [x] 3.3 Add `autocut/core/score.py` with rank normalization across segments and weighted composite score. Verify with unit tests: scores in 0 to 1, higher sharpness yields higher score when other metrics are equal, changing weights changes scores without touching metrics.

## 4. Cache

- [x] 4.1 Add `autocut/core/cache.py` with `cache_dir(config)`, `entry_path(key, config)`, `read_entry`, `write_entry` (npz plus json, temp file then rename). Verify with a unit test round trip in a temp cache dir and a test that a different `sample_fps` misses.
- [x] 4.2 Add `autocut cache` and `autocut cache prune --older-than <days>` commands. Verify with a `CliRunner` test on a temp cache dir.

## 5. Thumbnails and orchestration

- [x] 5.1 Add `autocut/core/thumbs.py` writing the midpoint JPEG and optional sprite. Verify with a unit test on synthetic frames asserting file existence and sprite width.
- [x] 5.2 Add `autocut/core/analyze.py` with `analyze_files(manifest, config, progress)` using a process pool for per-file decode and metrics, cache lookup first, then project-wide normalization, scoring, rules and thumbnails, saving the manifest at the end. Verify with an `ffmpeg` marked test over `tests/fixtures/synthetic/` asserting every file has at least one segment, `static.mp4` is rejected `no_motion`, `blurred.mp4` scores below `sharp_pan.mp4`, and `drone_embedded_srt.mp4` has an early segment rejected `low_altitude`.
- [x] 5.3 Implement cancellation via `AnalysisCancelled` raised from the callback. Verify with a test that cancels after the second file and asserts the manifest has segments for exactly two files.
- [x] 5.4 Extend `Segment` in `autocut/core/manifest.py` with `trimmed_start_s`, `trimmed_end_s`, `frame_count`, `analyzed_from`. Verify `tests/unit/test_manifest.py` passes with a new roundtrip case.
- [x] 5.5 Wire `autocut analyze` to run analysis after ingest, saving the manifest after each phase, with Rich progress. Verify with a `CliRunner` test on the synthetic folder asserting segments exist and a second run reports cache hits for every file.

## 6. Real footage validation

- [x] 6.1 Run `autocut analyze` on `AUTOCUT_REAL_FOOTAGE` into a scratch folder, record wall time, cache hit time on the second run, and the count of rejected segments per reason in a comment in `tests/integration/test_analyze_real.py` (marked `real_footage`, asserting at least one `low_altitude` rejection among drone files and that every Action 4 file was analyzed from its proxy).

  Result on the Sardinia set, 2026-09-03, Linux host with 16 physical cores and ffmpeg 8.0.1: 16 passed. 72 files, 77 segments. Cold run 221.5 s wall (about 3.1 s per file); second run 6.4 s with 72 of 72 cache hits, about 35 times faster; cache 8.1 MB. 43 of 72 files analyzed from their `.LRF` proxy, which is every Action 4 clip. Rejections: 13 of 77 segments, `low_altitude` 4, `too_short` 6, `no_motion` 3.

  Two findings changed the implementation. First, the low altitude rule could not fire as originally specified: the four clips that contain a takeoff are each one continuous shot (content difference peaking at 0.03 to 0.12, far below any cut threshold), so the segment covering the whole clip has a maximum height of 11 to 30 m. A telemetry driven split was added, described in `specs/segmentation/spec.md` and `design.md`, which cuts each shot where height crosses the threshold; the rule itself is unchanged and now rejects exactly those four takeoffs while their cruise segments survive. Second, one Action 4 clip is 33 ms long, and ffmpeg's `fps` filter emits nothing for it, so the file had no segment at all and was re-decoded on every run; the sampler now falls back to a single frame, which the length rule then rejects as `too_short`.

  Also observed: `-hwaccel auto` selects CUDA on this host and fails with `Cannot load libcuda.so.1`, and the software fallback added in task 1.2 handles it on every file.

- [x] 6.2 Run `make lint` and `make docker-test`, then commit on branch `feat/m1-analysis` following `sf-commit-convention` and open a pull request.

## 1. Sampler

- [ ] 1.1 Add `autocut/core/sampler.py` with `build_sample_command(path, fps, long_side, hwaccel) -> list[str]` and `sample_frames(path, probe, config) -> SampledFrames` (timestamps array, frames array `N x H x W x 3 uint8`, source proxy or original). Verify command construction with a unit test on the argument list and frame count with an `ffmpeg` marked test on `sharp_pan.mp4` (about 12 frames for 6 s at 2 fps).
- [ ] 1.2 Implement the software fallback when the hardware attempt fails. Verify with a unit test that fakes a failing first subprocess and asserts the second call has no `-hwaccel`.
- [ ] 1.3 Read from the proxy when attached and enabled. Verify with a unit test asserting the command targets the proxy path.

## 2. Metrics

- [ ] 2.1 Add `autocut/core/metrics.py` with pure functions `sharpness`, `clipping_fraction`, `motion_series`, `stability_series`, `colorfulness` and `frame_metrics(frames, source_class) -> FrameMetrics`. Verify with unit tests on synthetic NumPy images: blurred lower sharpness than sharp, white frame clipping near 1, identical frames motion 0, alternating frames high motion and low stability, gray frame colorfulness near 0.
- [ ] 2.2 Implement the center crop for `actioncam` sharpness. Verify with a test where edge noise raises full-frame sharpness but not center-crop sharpness.

## 3. Segmentation and rules

- [ ] 3.1 Add `autocut/core/segment.py` with `detect_shots(frames, timestamps, threshold, min_len) -> list[tuple[float, float]]` and `apply_trims(bounds, duration, source_class, config)`. Verify with an `ffmpeg` marked test on `multishot.mp4` asserting three segments with boundaries within 0.5 s of 3.0 and 6.0, and a unit test for the phone trim scenario.
- [ ] 3.2 Add `autocut/core/rules.py` with `apply_rules(segment, metrics, telemetry, config) -> str | None` implementing `too_short`, `low_altitude`, `no_motion`, `shaky`, `clipped` in that order. Verify with unit tests for every scenario in `specs/rejection-rules/spec.md`.
- [ ] 3.3 Add `autocut/core/score.py` with rank normalization across segments and weighted composite score. Verify with unit tests: scores in 0 to 1, higher sharpness yields higher score when other metrics are equal, changing weights changes scores without touching metrics.

## 4. Cache

- [ ] 4.1 Add `autocut/core/cache.py` with `cache_dir(config)`, `entry_path(key, config)`, `read_entry`, `write_entry` (npz plus json, temp file then rename). Verify with a unit test round trip in a temp cache dir and a test that a different `sample_fps` misses.
- [ ] 4.2 Add `autocut cache` and `autocut cache prune --older-than <days>` commands. Verify with a `CliRunner` test on a temp cache dir.

## 5. Thumbnails and orchestration

- [ ] 5.1 Add `autocut/core/thumbs.py` writing the midpoint JPEG and optional sprite. Verify with a unit test on synthetic frames asserting file existence and sprite width.
- [ ] 5.2 Add `autocut/core/analyze.py` with `analyze_files(manifest, config, progress)` using a process pool for per-file decode and metrics, cache lookup first, then project-wide normalization, scoring, rules and thumbnails, saving the manifest at the end. Verify with an `ffmpeg` marked test over `tests/fixtures/synthetic/` asserting every file has at least one segment, `static.mp4` is rejected `no_motion`, `blurred.mp4` scores below `sharp_pan.mp4`, and `drone_embedded_srt.mp4` has an early segment rejected `low_altitude`.
- [ ] 5.3 Implement cancellation via `AnalysisCancelled` raised from the callback. Verify with a test that cancels after the second file and asserts the manifest has segments for exactly two files.
- [ ] 5.4 Extend `Segment` in `autocut/core/manifest.py` with `trimmed_start_s`, `trimmed_end_s`, `frame_count`, `analyzed_from`. Verify `tests/unit/test_manifest.py` passes with a new roundtrip case.
- [ ] 5.5 Wire `autocut analyze` to run analysis after ingest, saving the manifest after each phase, with Rich progress. Verify with a `CliRunner` test on the synthetic folder asserting segments exist and a second run reports cache hits for every file.

## 6. Real footage validation

- [ ] 6.1 Run `autocut analyze` on `AUTOCUT_REAL_FOOTAGE` into a scratch folder, record wall time, cache hit time on the second run, and the count of rejected segments per reason in a comment in `tests/integration/test_analyze_real.py` (marked `real_footage`, asserting at least one `low_altitude` rejection among drone files and that every Action 4 file was analyzed from its proxy).
- [ ] 6.2 Run `make lint` and `make docker-test`, then commit on branch `feat/m1-analysis` following `sf-commit-convention` and open a pull request.

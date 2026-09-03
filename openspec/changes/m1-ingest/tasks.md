## 1. Probe

- [ ] 1.1 Add `autocut/core/probe.py` with `ProbeResult` (Pydantic) and `probe_file(path) -> ProbeResult` running ffprobe JSON, parsing rotation from side data with legacy tag fallback, GPS from ISO 6709 `location`, bit depth from pixel format, creation time, make and model tags, subtitle and data stream inventory. Verify with unit tests on captured ffprobe JSON for the three device families (store JSON under `tests/data/ffprobe/`).
- [ ] 1.2 Add `tests/unit/test_probe_ffmpeg.py` marked `ffmpeg` that probes `tests/fixtures/synthetic/vertical_rot90.mp4` and `hevc_10bit.mp4` and asserts rotation -90 and bit depth 10.
- [ ] 1.3 Handle ffprobe failure by returning a `ProbeResult` with `error` set. Verify with a unit test on a non-video file.

## 2. Telemetry adapters

- [ ] 2.1 Add `autocut/core/telemetry/__init__.py` with `TelemetrySample`, `TelemetrySeries`, `TelemetrySummary` models and the `TelemetryAdapter` protocol. Verify with mypy strict passing.
- [ ] 2.2 Add `autocut/core/telemetry/dji.py` with the DJI cue regex parser and the two adapters (`DjiEmbeddedSrtAdapter`, `DjiSidecarSrtAdapter`). Verify with unit tests on the cue string from SPEC.md section 4 and on a malformed cue.
- [ ] 2.3 Implement embedded subtitle extraction via `ffmpeg -map 0:s:<idx> -f srt -`. Verify with an `ffmpeg` marked test on `drone_embedded_srt.mp4` asserting six samples with heights 0.5 to 30.0.
- [ ] 2.4 Add `detect_telemetry(probe, path) -> tuple[TelemetryKind, TelemetrySeries | None]` trying adapters in order. Verify with tests for embedded, sidecar and none.

## 3. Classification

- [ ] 3.1 Add `autocut/core/classify.py` with `classify(probe, telemetry_kind, rel_path, overrides) -> Classification(source_class, signal, overridden)`. Verify with unit tests covering the scenarios in `specs/source-classification/spec.md`.
- [ ] 3.2 Add glob override handling with last match wins. Verify with a unit test using two overlapping globs.

## 4. Ingest

- [ ] 4.1 Add `autocut/core/cachekey.py` with `cache_key(path) -> str` (blake2b over size, mtime ns, first and last 1 MB). Verify with unit tests for copy equality and content difference on temp files.
- [ ] 4.2 Add `autocut/core/ingest.py` with `scan(sources, config) -> list[Path]` honoring accepted extensions, skipping hidden, `.part`, `.lrv` and `.lrf`. Verify with a unit test on a temp folder tree.
- [ ] 4.3 Add proxy discovery `find_proxy(path, config) -> Path | None`. Verify with unit tests for `.LRF`, `.lrv`, and disabled proxies.
- [ ] 4.4 Add `ingest(sources, config, progress) -> list[SourceFile]` using a `ProcessPoolExecutor`, emitting a `probe` progress event per file, assigning chronological order with path tiebreak. Verify with an `ffmpeg` marked test over `tests/fixtures/synthetic/` asserting count, order and no stdout output from the core.
- [ ] 4.5 Extend `SourceFile` in `autocut/core/manifest.py` with `class_signal`, `telemetry_summary`, `error`, `subtitle_streams`, `data_streams`. Verify `tests/unit/test_manifest.py` still passes and add a roundtrip case with a summary.

## 5. CLI

- [ ] 5.1 Implement `autocut analyze` ingest path: load config, run ingest with a Rich progress bar, create or update the manifest in `--out`, exit non-zero with a message when no files are found. Verify with a Typer `CliRunner` test on the synthetic folder asserting `manifest.json` exists and validates, and one on an empty folder asserting non-zero exit.
- [ ] 5.2 Add `--no-proxies` and `--workers` flags mapped onto config. Verify with `--help` output test.

## 6. Real footage validation

- [ ] 6.1 Add `tests/integration/test_ingest_real.py` marked `real_footage` asserting that every DJI Mini 2 file is `drone` with `dji_embedded_srt`, every `_D.MP4` Action 4 file is `actioncam` with an `.LRF` proxy, and every `VID_` Xiaomi file is `phone`. Run it locally with `AUTOCUT_REAL_FOOTAGE="$HOME/Documents/autocut/test sardegna"` and record the result in the task.
- [ ] 6.2 Run `make lint` and `make docker-test`, then commit on branch `feat/m1-ingest` following `sf-commit-convention` and open a pull request.

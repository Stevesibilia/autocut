## Why

Nothing in the pipeline can run until AutoCut knows which files exist, what they contain, and which telemetry and proxies travel with them. Milestone M1 starts here: `autocut analyze` must scan the source folders and write a `manifest.json` describing every file, so that the analysis change can attach segments and metrics to it.

## What Changes

- Recursive scan of one or more source folders for accepted video extensions, skipping proxy files as sources.
- `ffprobe` based probing of each file: duration, resolution, rotation, fps, codec, pixel format, bit depth, color transfer, creation time, GPS and make/model tags, stream inventory.
- Proxy discovery: `.lrv` and `.lrf` files with the same stem are attached to the source file as the analysis proxy.
- Telemetry adapter interface with the first adapter for the DJI embedded `mov_text` subtitle stream, producing per-second height, speed, GPS, ISO and shutter. A sidecar `.SRT` adapter shares the same parser.
- Capability based source classification into `drone`, `actioncam`, `phone`, `reflex` or `generic`, overridable per glob in `autocut.toml`.
- Global chronological ordering on creation time with mtime fallback.
- Cache key computation (size, mtime, first and last 1 MB hash) for each file.
- `autocut analyze` command writes the manifest with the `files` section populated and reports progress through the core event callback.

## Capabilities

### New Capabilities

- `footage-ingest`: scanning source folders, probing files, discovering proxies, computing cache keys and ordering files chronologically into the manifest.
- `telemetry-adapters`: detecting and parsing per-file telemetry (DJI embedded subtitle stream and sidecar SRT) into a common time series.
- `source-classification`: deriving the source class of a file from probed signals and telemetry, with user overrides.

### Modified Capabilities

None. The project has no main specs yet.

## Impact

- New modules under `autocut/core/`: `ingest.py`, `probe.py`, `telemetry/` package, `classify.py`, `cachekey.py`.
- `autocut/cli/main.py`: `analyze` command gains a real body for the ingest part; later changes extend it.
- `autocut/core/manifest.py`: `SourceFile` gains a `telemetry_summary` field (min and max height, mean speed, GPS bounds) so the report and rules can use it without reparsing.
- External binaries: `ffprobe` and `ffmpeg` required at runtime, already declared in the README.
- Tests: synthetic fixtures `drone_embedded_srt.mp4`, `vertical_rot90.mp4`, `hevc_10bit.mp4` exercise telemetry, rotation and bit depth. Private and real footage tests validate classification on the Sardinia set.

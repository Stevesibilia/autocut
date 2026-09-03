## Why

With files ingested, AutoCut must look at the pictures. This change adds sampled frame decoding, per-frame quality metrics, shot segmentation, rejection rules and the global analysis cache, so that `autocut analyze` produces scored segments that the selection milestone can rank. It completes the analysis half of milestone M1 (SPEC.md section 15).

## What Changes

- Frame sampler based on an ffmpeg pipe (`-hwaccel auto`, `fps`, `scale`, raw RGB), reading the proxy when present.
- Shot segmentation per file with content based scene detection and a minimum segment length.
- Per sampled frame metrics: sharpness (Laplacian variance, center crop for action cams), exposure clipping, motion, stability, colorfulness.
- Per segment aggregation into the `Metrics` model, composite score from configurable weights.
- Rejection rules before scoring: low altitude from telemetry, no motion, shaky, per-class head and tail trim, minimum duration.
- Global analysis cache keyed on the file cache key plus analysis schema version, holding per-frame arrays and telemetry samples, so re-running analysis on known files reads from disk.
- One thumbnail per segment and optional sprite strip written under `thumbs/`.
- `autocut analyze` extended to run segmentation and analysis after ingest and to fill the `segments` section of the manifest.

## Capabilities

### New Capabilities

- `frame-analysis`: sampled decoding, per-frame metrics, per-segment aggregation, composite score and thumbnails.
- `segmentation`: splitting a file into shot segments and trimming heads and tails.
- `rejection-rules`: deterministic pre-scoring rejection with recorded reasons.
- `analysis-cache`: global on-disk cache of analysis results keyed on file fingerprint and schema version.

### Modified Capabilities

- `footage-ingest`: the `autocut analyze` command now continues into segmentation and analysis after ingest and writes segments into the manifest.

## Impact

- New modules under `autocut/core/`: `sampler.py`, `metrics.py`, `segment.py`, `rules.py`, `score.py`, `cache.py`, `thumbs.py`, `analyze.py` (orchestration).
- `autocut/core/manifest.py`: `Segment` gains `trimmed_start_s`, `trimmed_end_s`, `frame_count`; `Metrics` unchanged.
- Dependencies already declared: NumPy, OpenCV headless, PySceneDetect, Pillow, platformdirs.
- Runtime: hardware decoding through ffmpeg when available; analysis time on the Sardinia set is measured and recorded.
- Tests: synthetic fixtures for sharp, blurred, over and under exposed, static, shaky, multi-shot and telemetry; metric expectations are relative (blurred sharpness below sharp sharpness) rather than absolute.

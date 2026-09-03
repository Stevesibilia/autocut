# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Project specification in English with the decisions from the 2026-09-03 review.
- Architecture decision records 1 to 8.
- Repository skeleton: core, cli and gui packages, configuration and manifest schemas, CLI command stubs.
- Synthetic fixture generator and test scaffolding.
- Docker development environment and GitHub Actions workflows for CI and macOS release builds.
- Best window search: the sub-window of target duration with the highest mean per-frame score, stored as a centre and a target duration.
- Classic similarity signals, each switchable: perceptual hash and colour histogram on the segment thumbnail, GPS distance, timestamp distance and motion profile correlation.
- Greedy clip selection with a similarity penalty, per-file, per-cluster and total caps, a minimum share per class and a minimum temporal gap.
- Visual clusters over the combined similarity, so near duplicates group in the report.
- `autocut select` with `--max-clips`, `--duration` and `--diversity`, and `autocut run` chaining analyze, select and report.
- ffmpeg command builder for one clip as a pure function, covering precise re-encode and fast stream copy, frame rate and resolution normalization, pixel format conversion, per-class audio removal, automatic slow motion, the three vertical strategies, and the LUT and lens correction hooks. `export.fps = "auto"` takes the frame rate that the most selected clips reach by whole-number division, lowest on a tie.
- Output naming `{index:03d}_{date}_{class}_{tag}_{duration}s.mp4` into `_selects/`, with `_rejects/` on request and retired outputs moved to `_selects/_stale/`.
- `autocut export` with `--no-audio`, `--fps`, `--fast` and `--rejects`, parallel over clips and resumable: a clip whose output matches its recorded settings is skipped.
- Synthetic fixtures for a clip with an audio track and a 50 fps clip.

### Changed

- The review report lists selected segments first, with their edit order, best window bounds, visual cluster and the near duplicate a candidate lost to.
- Selection holds back display-vertical candidates when `export.vertical_strategy` is `exclude`, marking them with the reason `vertical` while they stay candidates, so the report shows them as excluded by policy rather than rejected on quality.
- The review report links each selected card to its exported file and marks fast cuts and clips resampled from another frame rate.

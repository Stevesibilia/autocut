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

### Changed

- The review report lists selected segments first, with their edit order, best window bounds, visual cluster and the near duplicate a candidate lost to.

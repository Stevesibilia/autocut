## Purpose

The Analysis screen runs the long part of the pipeline where the user can see it, stop it and pick it up again.

## ADDED Requirements

### Requirement: Pipeline run with progress

The screen SHALL run analyze, then embed, tag and describe when enabled, through the worker, showing a progress bar, the current file name, files done over total, elapsed time and an estimate of time left computed from the mean per-file time so far. Each stage SHALL be shown as a step with its own status.

#### Scenario: Progress detail

- **WHEN** 30 of 72 files are analyzed after 90 s
- **THEN** the screen shows 30 of 72, the current file, 90 s elapsed and about 126 s left

### Requirement: Cancel and resume

Cancel SHALL stop between files. The screen SHALL then offer Resume, which analyzes only files without a cache entry and segments, so a resumed run does no repeated decoding.

#### Scenario: Resume

- **WHEN** a run was cancelled at 30 of 72 and the user resumes
- **THEN** 42 files are analyzed and the manifest ends with 72

### Requirement: Warnings and results

Warnings recorded by the core (decoder fallback, telemetry without samples, skipped embeddings, description failures) SHALL be listed on completion, and the screen SHALL show a summary: files per class, segments per outcome and reason, cache hits, cloud requests and cost.

#### Scenario: Summary

- **WHEN** analysis completes
- **THEN** the summary matches the report header counts and the Review screen enables

### Requirement: Re-analysis controls

The screen SHALL offer Re-run analysis (cache hit, no decoding) after configuration changes that affect scoring, and Clear cache for this project with a size shown.

#### Scenario: Weights changed

- **WHEN** the user changes a weight in Settings and re-runs
- **THEN** analysis completes from cache in seconds and scores update

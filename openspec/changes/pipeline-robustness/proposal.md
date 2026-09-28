## Why

Issue #78, from the 2026-09-28 project review. Bad input takes down more than it should:

- A clip that makes ffmpeg write a lot of decode errors can hang its worker forever, because the sampler reads stderr only after stdout ends.
- One unexpected exception in one worker aborts the whole run, and every result already finished is thrown away.
- A truncated cache entry raises instead of being recomputed, and the two files of an entry can drift apart after a crash.
- A misspelled `--config` path or key is silently ignored; a bad TOML file or an invalid manifest prints a traceback.
- A timed-out export leaves a partial clip under its final name, Ctrl-C during analysis loses the partial results, and a missing ffmpeg is reported once per file instead of once.

## What Changes

- The sampler SHALL drain ffmpeg's stderr while it reads frames, so the pipe can never fill.
- Each worker result SHALL be collected individually: an exception from one file SHALL become that file's error and SHALL NOT stop the others. This holds for ingest, analysis and export.
- Ctrl-C during analysis SHALL stop the run like a cancellation: files already finished are kept and saved, and the CLI exits with status 130.
- Ingest and export SHALL check that `ffprobe` and `ffmpeg` are on PATH before starting any worker, and SHALL fail once with a clear error when they are not.
- A cache entry that cannot be read for any reason SHALL count as a miss. Both files of an entry SHALL carry a shared write token and SHALL be ignored when the tokens differ; an entry whose `file_key` does not match SHALL be ignored. `prune` SHALL remove orphaned files.
- Configuration SHALL reject unknown keys and out-of-range values. The CLI SHALL refuse an explicit `--config` path that does not exist, and SHALL report an unreadable configuration or manifest in one line with exit status 1.
- A failed or timed-out export SHALL never leave a file at the clip's output path.
- Loading a manifest that needs a migration SHALL first copy the original file next to it.

## Capabilities

### New Capabilities

- `configuration`: loading and validating `autocut.toml`.

### Modified Capabilities

- `frame-analysis`: failure isolation, interruption, stderr draining.
- `analysis-cache`: corrupt and mismatched entries.
- `clip-export`: no partial output, failure isolation.
- `footage-ingest`: tool preflight, failure isolation.
- `project-manifest`: unreadable manifests reported, backup before migration.

## Impact

`autocut/core/sampler.py`, `analyze.py`, `ingest.py`, `export.py`, `cache.py`, `config.py`, `manifest.py`, `probe.py`, `autocut/cli/main.py`. Tests in `tests/unit/`. `SPEC.md` and `CHANGELOG.md`. No manifest schema bump and no `ANALYSIS_SCHEMA_VERSION` bump: entries written before this change stay valid (design decision 5).

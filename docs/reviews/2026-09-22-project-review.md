# Project review, 2026-09-22

A review of `main` at `9afece0`, after milestone M5. It covers the state of the code, the defects found, and the upgrades worth making next.

## Verdict

AutoCut is in strong shape for a personal tool.

- **Lint.** `make lint` passes: ruff, format and strict mypy clean across 89 source files.
- **Tests.** 1,734 passed, 48 skipped, 1 flaky (see finding 1). A full run takes about four minutes.
- **Architecture.** `autocut/core` imports no CLI or GUI code and never prints. ffmpeg is always called with argument lists, never shell strings. Every tunable lives in `config.py`. The eight broad `except Exception` handlers each carry a comment saying why.
- **Process.** Ten ADRs, 25 archived openspec changes, Conventional Commits, pull requests only. Comments explain why, not what.

The main risk is not the code. The analysis performance target has never been measured on the M4, and the release pipeline cannot produce a release yet.

## Findings

### 1. Flaky GUI test on `main`

`tests/unit/test_gui_review.py::test_coming_back_selects_the_clip_that_was_playing` failed in a full run with `assert 'f0:0' == 'f2:0'`, then passed three times when run alone. It came in with PR #66.

Likely cause, not confirmed: during `qtbot.wait(50)` the real `QMediaPlayer` emits a position update that announces clip 0 again and overwrites `_current_order`. Under the load of a full run the media loads more slowly, so the signal lands inside the wait.

**Fix.** Pause the player or block its signals before calling `_announce`, or drop the wait. Until then the `gui` CI job will fail at random.

### 2. `release.yml` cannot succeed

The workflow runs `make dmg`, which is a placeholder that exits with status 1. Every `v*` tag produces a failed run.

**Fix.** Disable the tag trigger until M6, or build a wheel as the release artifact in the meantime.

### 3. The manifest has no version guard

`Manifest.load` in `autocut/core/manifest.py` never checks `schema_version`. Pydantic ignores unknown fields by default, so a manifest written by a newer build loses those fields on the next save. The GUI autosaves on a debounce, so this happens without the user doing anything. AGENTS.md promises a migration on every schema bump, but no migration step exists yet.

**Fix.** Refuse to load `schema_version > MANIFEST_SCHEMA_VERSION` with a clear error, and add a `_migrate(dict) -> dict` step now while the version is still 1.

### 4. The cache key breaks on copies

`autocut/core/cachekey.py` hashes `st_mtime_ns`, yet its docstring says a copied file keeps its cache entry. Copies made with `cp`, with `scp` or `rsync` without `-t`/`-p`, or read from an exFAT SD card with coarse timestamps get a different mtime. The result is a cache miss and a full re-analysis of 4K footage.

**Fix.** Drop mtime from the key, or round it to whole seconds, and hash a middle chunk alongside the first and last megabyte. Camera files are not edited in place, so size plus sampled content is enough.

### 5. Documentation drift

- The README says M5 is in progress ("its first change ships the project and analysis screens"), while SPEC §15 marks M5 complete.
- SPEC §6 says frame sampling uses `-hwaccel auto`, while SPEC §12 says `auto` never lets ffmpeg choose.
- `specifiche-autocut.it.md` (33 KB) has likely fallen behind `SPEC.md` (66 KB), and AGENTS.md asks for English everywhere. Archive or delete it.
- `pyproject.toml` still says version `0.0.1` after five milestones.

### 6. No lock file

ADR 7 already requires pinned versions for the bundle. The current lower-bound-only constraints would let a future numpy 3 or opencv 5 in unchecked.

**Fix.** Add a lock with `uv lock` or `pip-compile` before M6 starts.

### 7. CI supply chain

- Actions are pinned to tags (`@v4`), not commit SHAs. This matters most for `softprops/action-gh-release`, which runs with release write permission.
- No Dependabot configuration keeps the actions current.
- Pushes to `main` are not tested again, which is how the flaky test in finding 1 went unnoticed.

### 8. Licensing, if the app is ever shared

The bundle plan includes a static ffmpeg. A build with `libx264` is GPL, which conflicts with the `Proprietary` license once the `.dmg` is distributed. For personal use this changes nothing; check the ffmpeg build flags during M6.

## Upgrades

### Quick wins on signals already computed

- **Aesthetic score (M4b).** The LAION aesthetic predictor is a small linear head on CLIP embeddings, which the cache already holds. No new decode, and a likely large gain in ranking quality.
- **Face detection (M4b).** OpenCV's YuNet ships in `opencv-python-headless`, so no new dependency. It gives the `family` profile a "people present" signal.
- **Energy matched sync.** The beat grid and waveform envelope already exist. Place high motion clips on the loud sections of the track, and cut on downbeats or 4 and 8 bar phrases rather than on any beat.

### Worth doing

- **Benchmark script.** A `scripts/bench.py` that records the time of each stage and compares videotoolbox with software decoding on the M4. The 100 GB in 30 minutes target is the main open promise in the specification.
- **Audio signals.** Use librosa to detect speech, laughter and wind noise. Keep family moments with natural sound, penalise clips whose audio wind has ruined.
- **Action 4 gyro.** Parse the `djmd` stream for a real shake signal instead of inferring it from the image. Already listed as an open item.
- **Local vision model fallback.** A small model through MLX or Ollama so captions and tags work offline, which fits ADR 4 better than OpenRouter alone.

### Later

- **Vertical export.** A 9:16 mode with a smart crop driven by faces and saliency, for reels, instead of excluding vertical clips.
- **Timeline export.** Optional OTIO or FCPXML output for DaVinci Resolve or Final Cut. CapCut has no import format, so the numbered clips stay the default.
- **Stabilization.** ffmpeg `vidstab` as an opt-in for shaky action camera clips.

## Suggested order

1. Findings 1 to 4. They are small, and finding 3 is the only one that can lose user work.
2. The benchmark script and the aesthetic score.
3. The lock file and CI hardening, as part of starting M6.

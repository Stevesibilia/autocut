## 1. Sampler drains stderr (design decision 1), one commit

- [x] 1.1 Rewrite `read_frames` in `autocut/core/sampler.py` as in decision 1.
- [x] 1.2 Tests in `tests/unit/test_sampler.py`, running a real `python -c` child instead of ffmpeg so no binary is needed:
  - a child that writes 1 MiB to stderr before writing two whole frames to stdout returns both frames, exit code 0, and the stderr tail, within a few seconds (use `pytest`'s `timeout` only if the plugin is installed; otherwise assert elapsed time);
  - a child that exits non-zero returns its code and the last stderr bytes;
  - the kept stderr is at most 65536 bytes.
- [x] 1.3 Commit: `fix(core): drain ffmpeg stderr while sampling frames`.

## 2. Failure isolation and Ctrl-C (decisions 2 and 3), one commit

- [x] 2.1 Guard every `future.result()` and the sequential calls in `analyze_files`, `ingest` and `export._run`, as in decision 2.
- [x] 2.2 `_ignore_sigint` initializer and the `KeyboardInterrupt` handling in `analyze_files`, as in decision 3.
- [x] 2.3 Tests:
  - `tests/unit/test_analyze.py`: with `workers=1` and `analyze_file` monkeypatched to raise `RuntimeError` for one of three files, the run completes, that file's result has an error starting `worker failed:`, the other two have segments, and `manifest.analysis.files_failed == 1`;
  - the same with a progress callback that raises `KeyboardInterrupt` after the first file: `AnalysisCancelled` is raised, `manifest.analysis.completed` is `False`, and the first file's segments are present;
  - `tests/unit/test_ingest.py`: `ingest_file` raising for one file gives that file an error and keeps the others;
  - `tests/unit/test_export.py`: `export_one` raising for one job records that clip as failed and exports the others.
  - Pool branches: one test per module with `workers=2` that makes one job raise inside the worker. The worker function must be importable by a spawn child, so use a fixture file that makes the real code fail (for example a path whose probe returns garbage) rather than a monkeypatch, which a spawn child does not see. If no such input exists for a module, say so in the hand-back and cover that module's pool branch by reading, not by test.
- [x] 2.4 Commit: `fix(core): keep a run going when one worker fails`.

## 3. Tool preflight (decision 4), one commit

- [x] 3.1 `ToolMissingError` and `require_tools` in `autocut/core/probe.py`; calls in `ingest()` and `export._run`; CLI catches in `analyze` and `export`.
- [x] 3.2 Tests: `require_tools` with `shutil.which` monkeypatched; `autocut analyze` on the synthetic fixtures with `shutil.which` returning `None` for `ffprobe` exits 1, prints `Missing tool` once and no traceback.
- [x] 3.3 Commit: `fix(core): check for ffmpeg and ffprobe before starting workers`.

## 4. Cache hardening (decision 5), one commit

- [x] 4.1 `read_entry`, `write_entry` and `prune` in `autocut/core/cache.py` as in decision 5.
- [x] 4.2 Tests in `tests/unit/test_cache.py`:
  - a `.npz` truncated to half its size reads as `None`;
  - an entry whose json `write_token` differs from the npz reads as `None`; one with the token in only one file reads as `None`; one with no token in either file (written by hand the old way) reads normally;
  - a json whose `file_key` differs reads as `None`;
  - `prune` removes an old orphaned `.json` and an old `.tmp` file, and returns only the count of `.npz` entries;
  - a write then read round-trips, and no `.tmp` file is left behind.
- [x] 4.3 Commit: `fix(core): treat any unreadable cache entry as a miss`.

## 5. Strict configuration and one-line errors (decisions 6 and 7), one commit

- [x] 5.1 `_Strict` base and bounds in `autocut/core/config.py`; `_load_config` and `_load_manifest` in `autocut/cli/main.py`; the migration backup in `_migrate`.
- [x] 5.2 Tests:
  - `tests/unit/test_config.py`: an unknown top-level key and an unknown nested key (`[analysis] sample_fsp = 3`) raise `ValidationError`; `sample_fps = 0` and `workers = 0` raise; `autocut.example.toml` loads;
  - CLI (`tests/unit/test_cli.py` or the closest file): `--config missing.toml` exits 1 with `Configuration not found`; a TOML syntax error and an unknown key each exit 1 with `Cannot read the configuration` and no `Traceback`; a manifest that is not JSON exits 1 with `Cannot open the project` and no `Traceback`;
  - `tests/unit/test_manifest.py`: with `MANIFEST_SCHEMA_VERSION` monkeypatched to 2 and a step registered, loading a version 1 file writes `manifest.v1.json.bak` identical to the original, and a second load does not overwrite an existing backup.
- [x] 5.3 Commit: `fix(core,cli): reject unknown configuration keys and report bad files in one line`.

## 6. No partial export (decision 8) and docs (decision 9), one commit

- [x] 6.1 Unlink in the `SubprocessError` branch of `export_one`.
- [x] 6.2 Test in `tests/unit/test_export.py`: `subprocess.run` monkeypatched to create the output file and raise `TimeoutExpired`; afterwards the file does not exist and the result carries an error.
- [x] 6.3 `SPEC.md` and `CHANGELOG.md` lines from decision 9.
- [x] 6.4 Commit: `fix(core): remove a partial clip after a failed export`.

## 7. Gates and hand-back

- [x] 7.1 `make lint` in the venv.
- [x] 7.2 `openspec validate pipeline-robustness --strict`.
- [x] 7.3 Hand the suites to a test runner: `make test`, then `make docker-test-gui`. Quote the counts as printed.
- [x] 7.4 Real run: `autocut analyze tests/fixtures/synthetic --out <tmpdir>` completes; then truncate one entry under the cache directory and run it again: the file is recomputed with no error. Put the output lines in the hand-back.
- [x] 7.5 Tick these boxes, push the branch and hand back.

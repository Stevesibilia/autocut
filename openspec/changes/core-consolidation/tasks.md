## Part A: brief 1

### 1. `run_tool` (design decision 1), one commit

- [x] 1.1 `autocut/core/proc.py` with `ToolRun`, `run_tool`, `first_stderr_line`, `ToolMissingError`, `require_tools`. Rewrite the ten sites, and update every import of `ToolMissingError`/`require_tools`.
- [x] 1.2 Tests in `tests/unit/test_proc.py`: success, non-zero exit, missing binary, timeout (a `python -c "import time; time.sleep(5)"` command with `timeout_s=0.2`), and `first_stderr_line` on blank-led text. The existing tests for the rewritten sites pass unchanged, or their changes are listed in the hand-back.
- [x] 1.3 Commit: `refactor(core): run external tools through one runner`.

### 2. Tunables (decision 2), one commit

- [x] 2.1 The new config fields and `TimeoutsConfig`. Replace the constants, pass `config.timeouts.*` where a config is in reach, and add the two "why this stays a constant" comments. Update `autocut.example.toml`.
- [x] 2.2 Tests:
  - every new field's default equals the old constant (one parametrized test);
  - `[timeouts] ffprobe_s = 5` reaches `probe_file` through `ingest_file` (monkeypatch `run_tool` to capture `timeout_s`);
  - `similarity.hash_share = 1.0` makes the visual similarity equal the hash similarity;
  - `export.workers = 3` is used.
- [x] 2.3 Commit: `refactor(core): move the remaining tunables into configuration`.

### 3. Cleanups (decision 3), one commit

- [x] 3.1 `ingest.scan` without `config`, and its callers.
- [x] 3.2 Commit: `refactor(core): drop the unused config parameter of scan`.

### Part A gates and hand-back

- [x] A.1 `make lint`, `openspec validate core-consolidation --strict`, and `make test` through the test runner. Quote the counts.
- [x] A.2 Real run: `autocut analyze tests/fixtures/synthetic --out <tmp>` then `autocut export`. Put the summary lines in the hand-back.
- [x] A.3 Tick the part A boxes, push, and hand back. Stop there: part B is a separate brief.

## Part B: brief 2, after #80 has merged

### 4. Pipeline (decision 4), one commit

- [x] 4.1 `autocut/core/pipeline.py`. The CLI `analyze`, `embed` and `describe` and the GUI `run_analysis` use it, and `AnalysisOutcome` moves.
- [x] 4.2 Tests:
  - `analyze_project` records the three cloud fields with a fake provider;
  - `AnalysisCancelled` from `analyze_files` propagates and embed is not called;
  - the GUI run records `cloud_model` (fake provider, cloud on);
  - `autocut analyze` output on the synthetic fixtures has the same lines as before (compare against a capture taken before the change, ignoring timings).
- [x] 4.3 Commit: `refactor(core): share one analysis pipeline between the cli and the gui`.

### 5. CLI split (decision 5), one commit

- [x] 5.1 Record the help snapshots first, then split `autocut/cli/main.py` and repoint the conftest monkeypatch.
- [x] 5.2 The help snapshot test, and every existing CLI test green.
- [x] 5.3 Commit: `refactor(cli): split the command line into one module per command group`.

### 6. Config defaults (decision 6) and docs, one commit

- [x] 6.1 Take the JSON snapshot of `AutocutConfig()` first, then create `config_defaults.py` and the default factories, and add the snapshot test.
- [x] 6.2 `SPEC.md`: the `[timeouts]` section and the new fields where configuration is described, and the pipeline sentence in §5. Add a `CHANGELOG.md` entry, and format the Markdown with `sjust format-md`.
- [x] 6.3 Commit: `refactor(core): move the default tag, genre and mood data out of config`.

### Part B gates and hand-back

- [ ] B.1 `make lint`, `openspec validate core-consolidation --strict`, `make test` and `make docker-test-gui` through the test runner.
- [ ] B.2 Real run: `autocut analyze`, `autocut select` and `autocut export` on the synthetic fixtures, plus `autocut gui` opened on that project with an analysis run started from the window. Describe what you saw.
- [ ] B.3 Tick the part B boxes, push, and hand back.

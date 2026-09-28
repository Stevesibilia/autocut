## Context

Mapped on `main` at `b2c1633` (after #78, #79 and #82):

- **Subprocess wrappers.** External tools run through ten hand-written `subprocess.run` sites:
  - `probe.probe_file` (`FFPROBE_TIMEOUT_S = 60.0`)
  - `render.probe_streams` (inline `timeout=60`, `render.py:203`)
  - `avmux.probe_duration` (inline `timeout=60`, `avmux.py:131`)
  - `avmux.run_ffmpeg` (caller-provided timeout: `CONCAT_TIMEOUT_S = 600.0`, `montage.PART_TIMEOUT_S = 300.0`)
  - `export.export_one` (`FFMPEG_TIMEOUT_S = 1800.0`)
  - `hwaccel.available_methods` and `hwaccel.verify` (`PROBE_TIMEOUT_S = 20.0`)
  - `beatsync.decode_audio` (`DECODE_TIMEOUT_S = 300.0`)
  - `telemetry/dji._run` (`EXTRACT_TIMEOUT_S = 60.0`)
  - `doctor._binary_version` (`VERSION_TIMEOUT_S = 10.0`)

  `sampler.read_frames` streams through `Popen` (`READ_TIMEOUT_S = 900.0`) and is a different shape. The first non-blank stderr line is taken by four identical `_first_line` copies: `probe.py:230`, `export.py:152`, `hwaccel.py:173`, `beatsync.py:133`. `avmux.run_ffmpeg` has the same loop inline. `ToolMissingError` and `require_tools` live in `probe.py`.

- **Hardcoded tunables outside `config.py`.** `classify.HIGH_FPS_THRESHOLD = 100.0` (`classify.py:47`, used at `:90`). `similarity.HISTOGRAM_BINS = 8` (`similarity.py:32`), and the `0.5 * hash + 0.5 * histogram` visual blend (`similarity.py:152`). The `probe.fps or 25` fallback (`analyze.py:127`). The `// 2` export worker divisor (`export.py:363`). The timeouts listed above.
- **`ingest.scan(sources, config=None)`** deletes its unused `config` (`ingest.py`, `del config`). `ingest` passes one, and five tests do not.
- **The analysis pipeline is written twice.** In the CLI, `analyze` in `autocut/cli/main.py` runs ingest, saves, then `analyze_files`, `_run_embed`, `_run_tag` and `_run_describe`. `_run_embed` records `analysis.embedding_model`/`embedding_device`, and `_run_describe` records `cloud_model`, `cloud_requests` and `cloud_cost_usd`. In the GUI, `ProjectState.run_analysis` and `_describe` in `autocut/gui/state.py` do the same work but never record the three cloud fields, and they keep their own `AnalysisOutcome` dataclass (`state.py:49`). On `AnalysisCancelled`, the CLI keeps going into embed, tag and describe, while the GUI stops. Progress events carry `stage` = `scan`, `probe`, `analyze`, `embed`, `tag` or `describe`.
- **`autocut/cli/main.py` is 1148 lines**, with every command, helper and printer in one file. Tests import `app` from it, `tests/conftest.py:145` monkeypatches `main.console`, and `tests/unit/test_cli.py:27` imports the module. The entry point `autocut = "autocut.cli.main:app"` is at `pyproject.toml:70`.
- **`autocut/core/config.py` is 981 lines**, of which about 330 are five default data blocks: `DEFAULT_TAG_GROUPS`, `DEFAULT_GENRE_ROWS`, `DEFAULT_ALLOWED_SECTIONS`, `DEFAULT_CALM_TO_ENERGETIC` and `DEFAULT_INTIMATE_TO_CINEMATIC`.

## Decisions

The change is built in two briefs. Part A (groups 1-3) touches only the core and can run now. Part B (groups 4-6) touches `autocut/gui/state.py`, so it starts after the GUI change for #80 has merged.

### Part A

**1. One runner for external tools, `autocut/core/proc.py`.**

```python
@dataclass(frozen=True, slots=True)
class ToolRun:
    returncode: int
    stdout: str
    stderr: str
    error: str | None = None  # set when the tool could not run or timed out

    @property
    def ok(self) -> bool: ...


def run_tool(command: list[str], *, timeout_s: float) -> ToolRun: ...


def first_stderr_line(text: str) -> str: ...
```

`run_tool` runs `subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False, stdin=subprocess.DEVNULL)` and never raises for the tool's own failure:

- `FileNotFoundError` gives `error=f"{command[0]} not found on PATH"`, `returncode=127`.
- `TimeoutExpired` gives `error=f"{command[0]} timed out after {timeout_s:g}s"`.
- `OSError` gives `error=str(exc)`.

`ToolMissingError` and `require_tools` move from `probe.py` to `proc.py`. Update every import; no re-export. Rewrite the ten sites above on `run_tool`, each keeping its current return type and messages. The four `_first_line` copies and the inline loop in `avmux.run_ffmpeg` become `first_stderr_line`, with unchanged semantics (the first non-blank line). `beatsync.decode_audio` reads bytes from stdout and cannot use the `text=True` runner. Leave its `subprocess.run` as it is, but switch it to `first_stderr_line`. `sampler.read_frames` is out of scope.
Rejected: changing to the last stderr line. Nothing showed the first line to be wrong, and the change would alter every user-facing error at once.

**2. Tunables move to config.** New fields, each with a `description`:

- `AnalysisConfig.high_fps_threshold: float = Field(100.0, gt=0)`, used by `classify` (the classifier gets the value through its existing config access, or as a parameter where it has none).
- `AnalysisConfig.fallback_fps: float = Field(25.0, gt=0)` for the `probe.fps or 25` fallback.
- `SimilarityConfig.histogram_bins: int = Field(8, ge=2, le=32)`.
- `SimilarityConfig.hash_share: float = Field(0.5, ge=0, le=1)`, the pHash share of the visual signal. The histogram gets `1 - hash_share`.
- `ExportConfig.workers: int | None = Field(None, ge=1)`. When unset, the default stays `max(1, (analysis.workers or physical_cores()) // 2)`.
- A new section `TimeoutsConfig` at `AutocutConfig.timeouts`, one field per timeout: `ffprobe_s=60`, `hwaccel_probe_s=20`, `sample_read_s=900`, `export_clip_s=1800`, `montage_part_s=300`, `concat_s=600`, `audio_decode_s=300`, `telemetry_extract_s=60`, `version_check_s=10`, all `gt=0`.

Module constants go away. Where a function has no config in reach (`decode_audio`, the dji adapter, `hwaccel.select`), its `timeout_s` keyword defaults to a module-level `_TIMEOUTS = TimeoutsConfig()`, the pattern `metrics.py` already uses with `_DEFAULTS`, and callers that have a config pass `config.timeouts.<name>`. `HASH_BITS = 64` and the colorfulness constant `0.3` stay: the first is fixed by the 8x8 hash structure, the second is part of the Hasler-Süsstrunk formula. Add a one-line comment saying so at each. Document every new field in `autocut.example.toml`.

Amended at review of part A:

- `classify` takes a keyword `high_fps_threshold` rather than a whole config.
- `color_histogram` takes `bins`, and the select helpers that call it gained a `config` parameter.
- `montage.concat_montage` and `render.check_parts_uniform` take a `timeout_s`.
- `export_one` receives `config.timeouts.export_clip_s` from `_run`, and the ffprobe helpers receive `config.timeouts.ffprobe_s` from `render_edit` and `build_montage`. These were first left on their module defaults and threaded at review, because a field that config cannot change misleads.
- `export_one` now removes the output file when ffmpeg is missing as well as on a timeout, because `ToolRun` reports both as `error`.
- The doctor tests patch `proc.subprocess.run`, since the call moved.
- The GUI's `decode_audio` call stays on the module default until part B.

**3. Small cleanups.** Remove the `config` parameter from `ingest.scan` and update its callers.

### Part B

**4. One analysis pipeline, `autocut/core/pipeline.py`.** Move `AnalysisOutcome` there from `gui/state.py` (amended at review: the planned `interrupted` field was dropped, because `analyze_project` re-raises `AnalysisCancelled` and no caller ever sees an outcome from an interrupted run). Add:

- `ingest_into(manifest, config, progress) -> list[SourceFile]`: runs `ingest(list(manifest.sources), config, progress)`, sets `manifest.files`, and returns the files.
- `run_embed(manifest, config, progress) -> EmbedResult`: `embed_project` plus the two `analysis.embedding_*` fields.
- `run_describe(manifest, config, progress, *, no_cloud=False) -> DescribeResult`: the `cloud_enabled` check, `OpenRouterProvider`, `describe_project`, and the three cloud fields on `manifest.analysis`, whichever front end runs it.
- `analyze_project(manifest, config, progress, *, no_cloud=False) -> AnalysisOutcome`: `analyze_files`, then `run_embed`, `tag_project` and `run_describe`. It fills the outcome counts. `AnalysisCancelled` from `analyze_files` propagates, so the later stages do not run.

The CLI's `analyze` calls `ingest_into`, saves, then calls `analyze_project` with one progress callback. That callback dispatches on `event.stage` to per-stage rich bars created on first use. It catches `AnalysisCancelled` as today, then writes the report and exits 130. The printed lines stay the same. `embed` and `describe` as standalone commands use `run_embed` and `run_describe`. The GUI's `run_analysis` becomes `ingest_into` plus `analyze_project`, and `_describe` goes away.

Two behaviour changes follow, and both are intended. On a cancel, the CLI no longer runs embed, tag and describe; it now matches the GUI. The GUI now records `cloud_model`, `cloud_requests` and `cloud_cost_usd` like the CLI.

**5. `autocut/cli` becomes a package of modules.**

- `autocut/cli/output.py` holds `console` and every `_print_*` helper.
- `autocut/cli/common.py` holds `ConfigOpt`, `NoCloudOpt`, `_load_config`, `_load_manifest`, `_one_line`, `_open_manifest` and `_open_project`.
- `autocut/cli/commands/` has one module per group:
  - `analyze.py`: analyze
  - `enrich.py`: embed, tag, describe
  - `keys.py`: the key sub-app
  - `doctor.py`, `select.py`, `soundtrack.py`, `report.py`, `sync.py`, `export.py`, `render.py`, `gui.py`, `run.py`
  - `cache.py`: the cache sub-app
- `autocut/cli/main.py` keeps `app`, `_root`, and the registration of every command and sub-app under its current name. Drop the `_` prefix on helpers that are now imported across modules.
- Every module refers to the console as `output.console` at call time, never through `from autocut.cli.output import console`, so the conftest monkeypatch can swap it. Point that monkeypatch at `autocut.cli.output.console`.

Before the move, record `autocut --help` and `autocut <command> --help` for every command in a test fixture file. Assert them unchanged after the move, then keep that test.

**6. Default data leaves `config.py`.** Move the five `DEFAULT_*` blocks to `autocut/core/config_defaults.py` as plain Python data (lists and dicts, no model constructors), so the module does not import `config.py`. `config.py` validates them in the fields' `default_factory` (`lambda: [GenreRow.model_validate(row) for row in DEFAULT_GENRE_ROWS]`, and so on). A test asserts that `AutocutConfig().model_dump(mode="json")` equals a JSON snapshot taken before the move.
Rejected: TOML files under `importlib.resources`. They would need packaging changes (hatch artifacts, and the PyInstaller spec of ADR 7) for no gain over a Python module.

**Rejected splits.** `manifest.py` (705 lines) is one coherent data model, and `Segment` alone is 200 lines of fields and docs. `select.py` (734 lines) is one algorithm whose private helpers call each other, and splitting it would only add imports. Both stay.

## Not touched

- Behaviour, apart from the two intended pipeline changes in decision 4.
- The manifest schema, the cache format, and any default value: every new config field defaults to the value it replaces.
- `sampler.read_frames`, and `manifest.py` and `select.py` apart from imports.

## Risks / Trade-offs

- **A message changes wording** after moving onto `run_tool`, and a test pins the old wording. Keep the old wording, unless it is the new generic "not found on PATH"/"timed out" text replacing a site-specific one. In that case report it and ask.
- **A command's `--help` changes** after the CLI split. The snapshot test catches it. Fix the registration, not the snapshot.
- **The default config changes** after decision 6. The JSON snapshot catches it. Fix the data, not the snapshot.
- **The GUI analysis screen reads fields of the old `AnalysisOutcome`.** The type keeps its fields and only moves, so imports change and nothing else.

## Migration Plan

None. Config files written before this change load unchanged, because every new field has a default.

## Open Questions

None.

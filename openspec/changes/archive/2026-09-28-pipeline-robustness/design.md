## Context

Findings from the 2026-09-28 review, checked against the code on `main` at `5f7aeec`:

- `read_frames` (`autocut/core/sampler.py:125`) opens stdout and stderr as pipes, reads stdout to EOF, and only then calls `communicate(timeout=READ_TIMEOUT_S)`. While stdout is being read nobody reads stderr, so ffmpeg blocks once about 64 KiB of stderr is queued, and the stdout read blocks with it. `READ_TIMEOUT_S` only covers the part after EOF.
- The pool loops call `future.result()` with no guard: `analyze_files` (`autocut/core/analyze.py:207`), `ingest` (`autocut/core/ingest.py:196`), `_run` in `autocut/core/export.py:374`. The worker functions catch the errors they expect, but anything else (a cv2 error, `OSError` from `write_entry` on a full disk, `BrokenProcessPool`) propagates out of the loop, so every result already finished is lost.
- `read_entry` (`autocut/core/cache.py:109`) catches `(OSError, ValueError, KeyError, json.JSONDecodeError)`. A truncated `.npz` raises `zipfile.BadZipFile`, `zlib.error` or `EOFError`, none of which is caught. `write_entry` (`cache.py:163`) replaces the `.npz` and then the `.json` (`:199-200`), so a crash between the two pairs new arrays with old metadata. The temporary names are fixed (`.npz.tmp`, `.json.tmp`), so two processes writing the same key collide. `meta["file_key"]` is written but never compared. `prune` (`:223`) walks only `*.npz`, so an orphaned `.json` or `.tmp` stays forever.
- `AutocutConfig.load` (`autocut/core/config.py:969`) returns defaults when the file is missing, which is right for the default `autocut.toml` but wrong for an explicit `--config` path (`autocut/cli/main.py:87`). No config model sets `extra`, so a misspelled key is dropped. `sample_fps` (`config.py:45`) has no bound and divides at `sampler.py:219`. `_load_config` catches nothing, so a TOML syntax error or a validation error is a traceback.
- `_load_manifest` (`cli/main.py:215`) catches only `ManifestVersionError`, so invalid JSON or a validation error is a traceback.
- `export_one` (`export.py:122`) returns early on `subprocess.SubprocessError`, which includes `TimeoutExpired`, without unlinking `plan.output`. The non-zero-exit branch below already unlinks it.
- The CLI treats `AnalysisCancelled` as an interruption (`cli/main.py:180-184`), but nothing raises it on Ctrl-C, so a `KeyboardInterrupt` passes through `analyze_files` before `_build_segments` runs and the finished files are lost.
- A missing `ffprobe` is reported by every worker as a per-file error. `_binary_check` (`autocut/core/doctor.py:103`) already knows how to look for a binary.

## Decisions

**1. Drain stderr on a thread.** In `read_frames`, start a daemon `threading.Thread` right after `Popen` that reads `process.stderr` in 4096-byte chunks until EOF and keeps only the last 65536 bytes in a `bytearray` (trim from the front). After the stdout loop, close stdout, `process.wait(timeout=READ_TIMEOUT_S)`, then join the thread with a 5-second timeout and decode what it kept. On `TimeoutExpired`: kill, wait, and return `(frames, 1, "ffmpeg timed out")` as today. The signature and return type stay the same, so the seven monkeypatched tests in `tests/unit/test_sampler.py` are untouched.
Rejected: a total deadline on the read loop. Decode time grows with clip length and machine speed, so any fixed cap would kill legitimate long 4K clips. The deadlock was the real defect.

**2. Collect each future on its own.** In the three pool loops, wrap `future.result()` in `try/except Exception as exc` and build a failed result from the job the future belongs to:

- analysis: `FileAnalysis(file_id=source.id, error=f"worker failed: {exc}")`;
- ingest: `SourceFile(id=f"path:{item.path}", path=item.path, error=f"worker failed: {exc}")`, the same fallback id `ingest_file` already uses when `cache_key` returns nothing;
- export: `ClipResult(job.segment.id, job.plan.output, job.digest, error=f"worker failed: {exc}")`.

Apply the same guard to the sequential branches (`workers == 1`), so both paths behave alike. Amended at review: `ingest`'s pool branch has no spawn-visible test, because no real input makes `ingest_file` raise (`probe_file` reports errors in its result, and `cache_key` and `find_proxy` swallow `OSError`). It uses the same guard as the other two modules and was checked by reading. The analyze and export pool branches are tested with real collisions, a directory where the cache file goes and a file where the output folder goes. `KeyboardInterrupt` is not an `Exception` and is handled by decision 3. Once the pool is broken, every remaining future raises `BrokenProcessPool` and each file gets its own error; that is the intended outcome.

**3. Ctrl-C is a cancellation.** In `analyze_files`, catch `KeyboardInterrupt` around both loops. On it, set `cancelled = AnalysisCancelled("interrupted")`, cancel the remaining futures, and leave the loop at once. Results that arrive afterwards are not collected: those files are analysed again on the next run. The existing code after the loop then builds segments, records `completed=False` and re-raises the `AnalysisCancelled`, which the CLI already turns into a partial save and exit code 130. For the pool branch, pass `initializer=_ignore_sigint` to the `ProcessPoolExecutor`, where `_ignore_sigint()` calls `signal.signal(signal.SIGINT, signal.SIG_IGN)`. Workers then do not print a traceback of their own; their ffmpeg children still get the terminal's SIGINT and exit, so the pool shuts down quickly. Ingest and export are left as they are: an interrupted ingest has nothing worth saving, and export is resumable by design.

**4. Preflight the binaries.** Add to `autocut/core/probe.py`:

```python
class ToolMissingError(RuntimeError):
    """A required external binary is not on PATH."""


def require_tools(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise ToolMissingError(f"{', '.join(missing)} not found on PATH. Run `autocut doctor`.")
```

Call `require_tools("ffprobe", "ffmpeg")` in `ingest()` after the scan and only when something was found, and `require_tools("ffmpeg")` in `_run` in `export.py` once there are pending jobs. The CLI's `analyze` command (around the `ingest` call, `cli/main.py:142`) and `export` command (around `export_clips`, `cli/main.py:880`) catch `ToolMissingError`; `run` goes through `analyze` and needs nothing of its own, print `[red]Missing tool[/red]: {error}` and exit 1. In the GUI the error reaches the worker's existing `failed` signal; no GUI change. `doctor.py` keeps its own check.

**5. Cache entries that cannot drift.**

- `read_entry` catches `Exception` around the read, not a list of types, because any unreadable entry is a miss by contract and numpy's zip layer raises several unrelated types. Also return `None` when `meta.get("file_key") != file_key`.
- `write_entry` generates `token = uuid.uuid4().hex`, stores it in the npz as the array `write_token` (`np.array(token)`) and in the json as `"write_token"`. `read_entry` compares them: when both are present and differ, or exactly one is present, the entry is a miss. When neither is present the entry predates this change and is accepted, so no `ANALYSIS_SCHEMA_VERSION` bump and no re-analysis of existing projects. `write_token` is not added to `ARRAY_NAMES`.
- Temporary names become `<key>.<pid>.npz.tmp` and `<key>.<pid>.json.tmp` (`os.getpid()`), so two writers never share a temp file.
- `prune` also deletes, when older than the cutoff, any `*.json` without its `.npz` and any `*.tmp`. The count it returns stays the number of `.npz` entries removed.

**6. Configuration is strict.** In `autocut/core/config.py` add `class _Strict(BaseModel): model_config = ConfigDict(extra="forbid")` and make every config model, `PerClass` included, inherit from it instead of `BaseModel`. Add bounds: `sample_fps: float = Field(default=2.0, gt=0)`, `workers: int | None = Field(default=None, ge=1, description=...)`, `sprite_max_frames: int = Field(default=60, ge=1)`. No other bounds in this change. `AutocutConfig.load` keeps its behaviour for `None` and missing files.
In `cli/main.py`, `_load_config` raises a clean error when `path` was given explicitly and does not exist (`[red]Configuration not found[/red]: {path}`, exit 1), and catches `(OSError, tomllib.TOMLDecodeError, pydantic.ValidationError)` around the load (`[red]Cannot read the configuration[/red] {path}: {error}`, exit 1). `autocut.example.toml` MUST still load: a test asserts it.
Rejected: `extra="forbid"` on the manifest, for the reason given in the manifest-version-guard design (decision 3).

**7. Manifest errors are one line, and migrations keep a backup.** `_load_manifest` catches `(OSError, ValueError)` instead of `ManifestVersionError` alone; `ManifestVersionError`, `json.JSONDecodeError` and `pydantic.ValidationError` are all `ValueError`. Same message prefix, exit 1. For a `ValidationError`, print only the first line of the error plus the error count, so the output stays one line. Amended at review: the configuration errors go through the same helper (`_one_line` in `cli/main.py`), so both kinds of file report one line.
In `_migrate` (`manifest.py:37`), right before the first step runs, copy the file with `shutil.copy2(path, backup)` where `backup = path.with_name(f"{path.stem}.v{version}.json.bak")`, unless that backup already exists. `Manifest.load` stays otherwise read-only.

**8. No partial clip.** In `export_one`, the `except subprocess.SubprocessError` branch unlinks `plan.output` (`missing_ok=True`) before returning, like the non-zero-exit branch already does.

**9. Docs.** One line per user-visible behaviour in `CHANGELOG.md` under `## [Unreleased]` → `### Fixed`. In `SPEC.md`: §7.3 gains a sentence that a failing file never stops the run and that Ctrl-C keeps finished files; §7.7 gains that a failed export leaves no file; §10 CLI gains that unknown configuration keys, out-of-range values and a missing `--config` path are errors, reported in one line.

## Not touched

- The pipelines' structure, pool types and the double probing: issue #82.
- Hardcoded timeouts such as `READ_TIMEOUT_S` and `FFMPEG_TIMEOUT_S`: issue #81 moves them to config.
- The GUI's own cancel and close paths: issue #80.
- `analysis_schema_version` checks on manifest load, and the manifest's `extra` policy.

## Risks / Trade-offs

- **Existing user configs with stale keys stop loading.** That is the point of decision 6, but if a test fixture or `autocut.example.toml` holds a key that no model declares, report it: do not add the key to a model and do not loosen `extra`.
- **Ignoring SIGINT in spawned workers affects the GUI.** The GUI runs analysis in a QThread, where SIGINT does not reach workers in a useful way. If a GUI test breaks, report it.
- **A thread in `read_frames` inside a spawn worker.** It is a daemon thread joined before return. If a test shows a leaked thread or a hang, report it; do not switch to `select`, which does not work on Windows pipes and is not needed on the two target platforms.
- **`except Exception` in `read_entry` hides programming errors.** Accepted for a cache whose contract is "unreadable means miss". Tests cover the real corruptions.

## Migration Plan

None. Cache entries and manifests written before this change keep loading.

## Open Questions

None.

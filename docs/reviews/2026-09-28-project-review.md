# Project review, 2026-09-28

A review of `main` at `5f7aeec`, after version 0.5.0. It covers what still breaks on bad input, where the toolchain drifted, and the upgrades worth making next. Every finding below was filed as an issue and checked against the code before filing.

## Verdict

The project is healthy. 1,793 tests are collected. A full run in the venv gave 1,745 passed and 48 skipped (the ai and real-footage markers), with 95% line coverage. There are no open issues or pull requests from before this review. The core rules hold: no CLI or GUI imports in `autocut/core`, no `print`, and ffmpeg always called with argument lists.

The weak spots are at the edges: bad input, dependencies that were never pinned, and a few long calls still made on the GUI thread.

## Findings

| #   | Area                | Finding                                                                                                                                                                                                                                                                                                                                                                        | Issue |
| --- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- |
| 1   | Core robustness     | The sampler reads ffmpeg's stderr only after stdout ends, so a noisy clip can hang a worker. One worker exception aborts a whole run. A truncated cache entry raises instead of missing. Config typos and a missing `--config` path are silent. Bad files print tracebacks. A timed-out export leaves a partial clip. Ctrl-C loses the analysis. There is no ffmpeg preflight. | #78   |
| 2   | Dependencies and CI | Open floors let OpenCV 5, scenedetect 0.7 (with a second `cv2` distribution) and librosa 1.0 in without review. There is no lock file. numpy 2.5 and librosa 1.0 need Python 3.12. The actions still run on Node 20. There is no coverage gate, audit or update bot. `release.yml` cannot publish a release.                                                                   | #79   |
| 3   | GUI threading       | Prompt refinement makes its HTTP call on the UI thread, and so do beat tracking and the export folder walk. Closing during a stage can block for 70 s and then save under a running worker.                                                                                                                                                                                    | #80   |
| 4   | Structure           | There are three ffprobe wrappers and four `_first_line` copies. The analysis pipeline is written twice, once in the CLI and once in the GUI. Several tunables are hardcoded outside `config.py`. `cli/main.py`, `config.py`, `manifest.py` and `select.py` are oversized.                                                                                                      | #81   |
| 5   | Performance         | Every file is probed twice. Subprocess-bound stages use process pools. The sampler buffers every frame, and GUI re-selection re-reads every cache entry.                                                                                                                                                                                                                       | #82   |
| 6   | Docs                | `AGENTS.md` still calls the GUI planned. The changelog has no 0.5.0 section. Two decisions have no ADR. Two archived changes carry unticked real-footage tasks.                                                                                                                                                                                                                | #83   |

## Decisions taken with the owner

- The new majors are accepted and locked, not capped (#79). The merge waits for a real-footage check (ADR 8), because OpenCV and librosa feed metrics and beat tracking.
- Python 3.11 is dropped (#79, ADR 11).
- All six issues are planned as OpenSpec changes and carried to a full release, with two implementers working in parallel on separate worktrees.

## Open items for the owner

- `m5-render-uniform-frame` task 3.3 is unticked in the archive, although its text records a completed real-footage validation. The archive is left as written.
- `m3-cloud-providers` task 4.1, the live provider validation on the Sardinia project, is still pending. It needs `OPENROUTER_API_KEY`, which only the owner can supply.
- There is still no `v0.5.0` tag. Whether to tag the current `main` retroactively is the owner's call.

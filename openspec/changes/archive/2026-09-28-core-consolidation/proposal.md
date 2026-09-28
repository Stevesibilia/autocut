## Why

Issue #81, from the 2026-09-28 project review. Ten hand-written subprocess sites and four copies of one helper handle external tools. Several thresholds and every timeout are hardcoded outside `config.py`, which AGENTS.md forbids. The analysis pipeline is written twice, once in the CLI and once in the GUI, and the copies have drifted: the GUI never records what the cloud pass cost. `autocut/cli/main.py` is 1148 lines. A third of `config.py` is default data.

## What Changes

- One `run_tool` runner in `autocut/core/proc.py` replaces the subprocess boilerplate.
- The remaining tunables move into configuration, including a new `[timeouts]` section. Every default stays the same.
- A shared `autocut/core/pipeline.py` runs ingest, analysis, embeddings, tags and descriptions for both front ends. The GUI SHALL record the cloud model, request count and cost like the CLI. A cancelled analysis SHALL stop before the later stages in both.
- `autocut/cli/main.py` is split into a package of command modules with identical commands and help.
- The default tag, genre and mood data move out of `config.py` into `config_defaults.py`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `configuration`: new tunable fields and the `[timeouts]` section.

## Impact

`autocut/core/` (proc.py and pipeline.py are new; probe, render, avmux, export, hwaccel, beatsync, telemetry/dji, doctor, classify, similarity, analyze, ingest, config, config_defaults), `autocut/cli/` (split into modules), `autocut/gui/state.py`, `autocut.example.toml`, `tests/`, `SPEC.md`, `CHANGELOG.md`. No schema or default change. Built in two briefs: part A (groups 1-3) now, part B (groups 4-6) after #80 merges.

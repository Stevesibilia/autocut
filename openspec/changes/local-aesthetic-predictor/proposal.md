## Why

Issue #96, roadmap milestone M4b. `Metrics.aesthetic` is filled only by the cloud `describe` step, which needs a paid key. SPEC §8 item 5 keeps a local predictor on CLIP embeddings (LAION weights) as the M4b option. Setting `weights.aesthetic` above 0 also crashes selection today with `KeyError: 'aesthetic'` in `window.frame_scores`, because `aesthetic` has no per-frame array.

## What Changes

- When `providers.aesthetic` is on and the `ai` extra is installed, a new aesthetic stage SHALL score every segment with LAION's aesthetic-predictor V1 linear head for ViT-B/32. The head is bundled, MIT, 3 KB. It runs on embeddings from a second CLIP tower, `ViT-B-32` with OpenAI weights, which is the space the head was trained in, applied to the cached per-shot thumbnails.
- The deduplication and tagging embeddings keep `ViT-B-32/laion2b_s34b_b79k`.
- A cloud judgment SHALL replace the local one. `Metrics.aesthetic_source` records which one a value is.
- Scores SHALL be recomputed after the stage when `weights.aesthetic` is above 0.
- The best-window search SHALL ignore scored metrics that have no per-frame array, which fixes the crash.
- `autocut embed`, `autocut analyze`, the GUI analysis summary and `doctor` SHALL report the stage.
- ADR 15 records the second tower and the bundled head.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frame-embeddings`: the local aesthetic stage.
- `best-window`: segment-only metrics do not shape the window.

## Impact

`autocut/core/aesthetic.py` (new), `autocut/core/models/` (bundled head), `embeddings.py`, `cache.py`, `manifest.py` (`Metrics.aesthetic_source`, additive, no schema bump), `describe.py`, `score.py`, `window.py`, `pipeline.py`, `doctor.py`, `config.py` (description only), `cli/commands/enrich.py`, `cli/commands/analyze.py`, `cli/output.py`, `gui/screens/analysis.py`, `pyproject.toml` (wheel artifacts only), tests, `SPEC.md`, `CHANGELOG.md`, `THIRD_PARTY_LICENSES.md`, `autocut.example.toml`, `docs/adr/0015-local-aesthetic-predictor.md`. No new dependency: torch and open_clip are already in the `ai` extra.

## Why

After analysis the manifest holds scored candidates but nothing chooses among them. This change delivers the core promise of AutoCut: from a few hundred candidates, pick 30 to 50 clips that are good, diverse and ordered, without a model. It is the first half of milestone M2 (SPEC.md section 7.4).

## What Changes

- Best window search per candidate: the sub-window of target duration with the highest mean per-frame score, stored as `best_center_s` and `target_duration_s` (ADR 5).
- Classic similarity signals, each switchable: perceptual hash plus color histogram on the segment thumbnail frame, GPS distance, timestamp distance, motion profile correlation.
- Greedy selection with similarity penalty (`score - lambda * max similarity to already selected`), honoring max clips per file per class, max total clips, minimum share per class, max clips per visual cluster, and minimum temporal gap.
- Visual clusters assigned from the combined similarity so the report and the future GUI can group near duplicates.
- Chronological `order` on selected segments by file creation time plus window offset.
- `autocut select` command with `--max-clips`, `--duration`, `--diversity` overrides, re-runnable: it resets previous selections but never touches rejections.
- `autocut run` shortcut chaining analyze, select and report.
- Report shows selected segments first, with their cluster and the reason a near duplicate lost.

## Capabilities

### New Capabilities

- `best-window`: locating the highest scoring sub-window inside a candidate.
- `similarity-signals`: computing pairwise similarity between candidates from classic signals.
- `clip-selection`: choosing the final ordered set under diversity, quota and cap constraints.

### Modified Capabilities

- `review-report`: selected segments and cluster grouping are shown.

## Impact

- New modules under `autocut/core/`: `window.py`, `similarity.py`, `select.py`.
- `autocut/core/manifest.py`: `Segment` gains `similarity_to_selected: float | None` and `lost_to: str | None` (id of the selected near duplicate); `Manifest` gains a `selection` block with the parameters used.
- `autocut/core/cache.py`: per-frame composite score is derived at select time from cached arrays; no schema change.
- Dependencies already declared: `imagehash`, `pillow`, NumPy.
- Depends on `m2-scoring-tuning`.

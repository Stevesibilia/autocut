## Context

Measured on the 72 file Sardinia manifest after `m1-analysis`: median sharpness 1343 for the 44 proxy sourced segments against 996 for the 33 original sourced ones, median score 0.562 against 0.430, ten of the top twelve segments proxy sourced. Highest motion anywhere 0.185 against a `max_motion` of 0.6. Clipping effectively zero on 76 of 77 segments. See proposal.md for why this matters now.

## Goals / Non-Goals

**Goals:**

- Scores that rank correctly within a class, computed from the existing cache without re-decoding.
- Rules whose thresholds can fire on the footage they are written for.

**Non-Goals:**

- Cross-class comparability of scores. Selection handles class balance with quotas.
- Making sharpness itself resolution independent. That would need per-file baselines and is not required once ranking is per class.
- Tuning for footage not yet seen (reflex).

## Decisions

**Per-class rank normalization.** Alternatives: normalize per `analyzed_from` (proxy or original), or divide sharpness by a per-file median. `analyzed_from` fixes the symptom but a future device with proxies for some clips and not others would split one class in two rank pools. Per-file baselines measure "best moment of this file", which is the best-window job, not the segment score. Per class is stable, explainable in the report, and matches how selection consumes scores.

**Shaky on stability alone.** Stability already encodes motion variability relative to mean motion, so gating it on absolute motion was redundant and, at 0.6, unreachable. The floor `shaky_min_motion` keeps near static jitter classified as `no_motion`, which is the more useful reason for a forgotten camera.

**Rule order.** `clipped` moves ahead of the motion rules. A blown out frame is a fact about the picture; motion rules describe the camera. The report card should show the picture defect.

**Thresholds from data, not guesses.** The implementer computes the per-class distribution of mean motion and stability over the real manifest and sets `min_motion`, `shaky_min_motion` and `min_stability` at recorded percentiles. Defaults are still config, tuning continues after selection exists.

## Risks / Trade-offs

- [Per-class normalization with tiny classes gives flat 0.5 scores] → documented; a class with one segment cannot be ranked anyway.
- [Thresholds tuned on one vacation] → recorded percentiles let the next dataset be compared; nothing is hardcoded.
- [Removing `rules.max_motion` breaks an existing `autocut.toml`] → no user config exists yet; the key is dropped without a migration and the example file is updated.

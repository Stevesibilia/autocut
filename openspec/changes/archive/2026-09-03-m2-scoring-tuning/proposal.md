## Why

The first report over the Sardinia footage (PR #3) showed three scoring defects that would make selection pick the wrong clips: proxy-analyzed action cam segments outscore everything because their sharpness is measured on a different rescale path, the `shaky` rule can never fire because its motion threshold is three times higher than any motion the metric produces, and the exposure weight ranks on noise. Selection (change `m2-select`) builds on these scores, so they are fixed first.

## What Changes

- Rank normalization runs per source class instead of across the whole project, so a drone segment competes with drone segments and an action cam segment with action cam segments. Cross-class balance is the job of the per-class quota in selection, not of the score.
- The `shaky` rule drops the unreachable `rules.max_motion` gate and fires on low stability alone, with a small motion floor so a static shot is still reported as `no_motion`.
- Rule evaluation order becomes `too_short`, `low_altitude`, `clipped`, `no_motion`, `shaky`, so an exposure defect is reported as such instead of being masked by the motion rules.
- The exposure weight defaults to zero. Clipping stays a rejection rule; it no longer contributes to ranking unless the user sets a weight.
- Default motion and stability thresholds are set from the measured distribution on the real footage and the percentiles used are recorded in the task list.
- `analysis_schema_version` is unchanged: no cached array changes, only aggregation and scoring, which re-run from cache.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frame-analysis`: the composite score normalizes per source class.
- `rejection-rules`: rule order, `shaky` rule definition and default thresholds change.

## Impact

- `autocut/core/score.py`: grouping by class before rank normalization.
- `autocut/core/rules.py`: new order, new `shaky` condition.
- `autocut/core/config.py`: `rules.max_motion` removed, `rules.shaky_min_motion` added, `weights.exposure` default 0, threshold defaults revised.
- `autocut.example.toml` and `SPEC.md` section 7.3 updated to match.
- Depends on change `m1-analysis` being merged and archived; the delta specs below modify requirements introduced there.

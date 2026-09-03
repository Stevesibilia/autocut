## 1. Measure

- [ ] 1.1 Write `scripts/metric_stats.py` that loads a manifest and prints, per source class, the 5th, 25th, 50th, 75th and 95th percentiles of segment motion, stability, sharpness and clipping. Verify by running it on the real Sardinia manifest and pasting the table into this task.
- [ ] 1.2 Choose defaults from that table: `min_motion` near the 5th percentile of motion, `shaky_min_motion` between `min_motion` and the median, `min_stability` near the 10th percentile of stability. Record the chosen values and the percentiles they correspond to in this task.

## 2. Scoring

- [ ] 2.1 Change `score_metrics` in `autocut/core/score.py` to take the source class per segment and rank normalize within each class. Verify with unit tests: two classes with disjoint sharpness ranges both produce a top score near 1, a single-segment class gets 0.5, changing weights still changes scores without touching metrics.
- [ ] 2.2 Set `weights.exposure` default to 0 in `autocut/core/config.py` and `autocut.example.toml`. Verify with a config default test.

## 3. Rules

- [ ] 3.1 Replace `rules.max_motion` with `rules.shaky_min_motion` in `autocut/core/config.py`, reorder `apply_rules` in `autocut/core/rules.py` to `too_short`, `low_altitude`, `clipped`, `no_motion`, `shaky`, and change the shaky condition. Verify with unit tests for every scenario in `specs/rejection-rules/spec.md`.
- [ ] 3.2 Update `REASONS` order and any report code that lists reasons. Verify the report test that counts reasons still passes.

## 4. Validation

- [ ] 4.1 Re-run `autocut analyze` on `AUTOCUT_REAL_FOOTAGE` (cache hit, no decoding), regenerate the report, and record in this task: rejections per reason, whether `shaky` fired and on which files, and the class of each of the top twelve segments. Verify that neither class holds all twelve.
- [ ] 4.2 Update `SPEC.md` section 7.3 (rule order, shaky definition, exposure weight) and `autocut.example.toml`. Verify prettier passes on the Markdown.
- [ ] 4.3 Run `make lint` and `make docker-test`, commit on branch `feat/m2-scoring-tuning` following `sf-commit-convention`, open a pull request.

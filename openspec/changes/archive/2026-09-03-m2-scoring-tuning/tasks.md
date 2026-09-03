## 1. Measure

- [x] 1.1 Write `scripts/metric_stats.py` that loads a manifest and prints, per source class, the 5th, 25th, 50th, 75th and 95th percentiles of segment motion, stability, sharpness and clipping. Verify by running it on the real Sardinia manifest and pasting the table into this task.

  A 10th percentile column and a pooled `all` row were added: the thresholds in config are single scalars, so they are chosen from the pooled distribution, and the per-class rows say whether one class drives it. Run on the 72 file Sardinia manifest, 77 segments:

  | class     | metric    | n   | p5     | p10    | p25    | p50    | p75    | p95    |
  | --------- | --------- | --- | ------ | ------ | ------ | ------ | ------ | ------ |
  | actioncam | motion    | 44  | 0.0072 | 0.0406 | 0.0515 | 0.0700 | 0.0832 | 0.1039 |
  | actioncam | stability | 44  | 0.6680 | 0.6895 | 0.7875 | 0.8457 | 0.9002 | 0.9522 |
  | actioncam | sharpness | 44  | 380    | 557    | 1001   | 1343   | 1658   | 1954   |
  | actioncam | clipping  | 44  | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0002 | 0.0011 |
  | drone     | motion    | 28  | 0.0133 | 0.0179 | 0.0260 | 0.0361 | 0.0691 | 0.0957 |
  | drone     | stability | 28  | 0.6223 | 0.7389 | 0.7835 | 0.8311 | 0.8788 | 0.9543 |
  | drone     | sharpness | 28  | 412    | 435    | 610    | 857    | 1302   | 1674   |
  | drone     | clipping  | 28  | 0.0000 | 0.0000 | 0.0000 | 0.0002 | 0.0003 | 0.0008 |
  | phone     | motion    | 5   | 0.0649 | 0.0682 | 0.0781 | 0.0810 | 0.0892 | 0.1655 |
  | phone     | stability | 5   | 0.7953 | 0.8018 | 0.8215 | 0.8957 | 0.9206 | 0.9841 |
  | phone     | sharpness | 5   | 1155   | 1174   | 1229   | 2256   | 2275   | 2457   |
  | phone     | clipping  | 5   | 0.0005 | 0.0006 | 0.0009 | 0.0009 | 0.0009 | 0.0012 |
  | all       | motion    | 77  | 0.0123 | 0.0225 | 0.0377 | 0.0668 | 0.0825 | 0.1047 |
  | all       | stability | 77  | 0.6634 | 0.7098 | 0.7882 | 0.8352 | 0.8957 | 0.9724 |
  | all       | sharpness | 77  | 399    | 482    | 814    | 1162   | 1497   | 2024   |
  | all       | clipping  | 77  | 0.0000 | 0.0000 | 0.0000 | 0.0001 | 0.0003 | 0.0012 |

  The sharpness rows are the defect this change fixes: the action cam median is 1343 against 857 for the drone, and the two distributions barely overlap, so a single project wide ranking sorts largely by which class was sampled from a proxy.

- [x] 1.2 Choose defaults from that table: `min_motion` near the 5th percentile of motion, `shaky_min_motion` between `min_motion` and the median, `min_stability` near the 10th percentile of stability. Record the chosen values and the percentiles they correspond to in this task.

  The percentile column is the share of the 77 pooled segments that falls below the chosen value, not the value at a round percentile. Both readings were in use and they differ: 0.015 leaves 7.8% of segments below it, while the value at the 7.8th percentile is 0.0190.

  | setting            | value | segments below | share | note                                       |
  | ------------------ | ----- | -------------- | ----- | ------------------------------------------ |
  | `min_motion`       | 0.015 | 6 of 77        | 7.8%  | the value at p5 is 0.0123, see below       |
  | `shaky_min_motion` | 0.04  | 20 of 77       | 26.0% | between `min_motion` and the median 0.0668 |
  | `min_stability`    | 0.71  | 8 of 77        | 10.4% | the value at p10 is 0.7098                 |

  `min_motion` is set slightly above the 5th percentile rather than at it. At 0.012 the only segment below the threshold is the one blown out clip, which the reordered rules now report as `clipped`, so `no_motion` would fire on nothing at all. That is the same defect this change exists to remove, so the value is the smallest round number above p5 at which the rule still fires on this footage. `max_clipped_fraction` is unchanged at 0.05: pooled p95 of clipping is 0.0012, so the rule stays rare by design and fires on exactly one segment.

## 2. Scoring

- [x] 2.1 Change `score_metrics` in `autocut/core/score.py` to take the source class per segment and rank normalize within each class. Verify with unit tests: two classes with disjoint sharpness ranges both produce a top score near 1, a single-segment class gets 0.5, changing weights still changes scores without touching metrics.
- [x] 2.2 Set `weights.exposure` default to 0 in `autocut/core/config.py` and `autocut.example.toml`. Verify with a config default test.

## 3. Rules

- [x] 3.1 Replace `rules.max_motion` with `rules.shaky_min_motion` in `autocut/core/config.py`, reorder `apply_rules` in `autocut/core/rules.py` to `too_short`, `low_altitude`, `clipped`, `no_motion`, `shaky`, and change the shaky condition. Verify with unit tests for every scenario in `specs/rejection-rules/spec.md`.
- [x] 3.2 Update `REASONS` order and any report code that lists reasons. Verify the report test that counts reasons still passes.

## 4. Validation

- [x] 4.1 Re-run `autocut analyze` on `AUTOCUT_REAL_FOOTAGE` (cache hit, no decoding), regenerate the report, and record in this task: rejections per reason, whether `shaky` fired and on which files, and the class of each of the top twelve segments. Verify that neither class holds all twelve.

  Re-run over the 72 files in 6.9 s, 72 of 72 from cache, no decoding. 77 segments, 17 rejected.

  | reason         | before | after |
  | -------------- | ------ | ----- |
  | `too_short`    | 6      | 6     |
  | `low_altitude` | 4      | 4     |
  | `shaky`        | 0      | 5     |
  | `no_motion`    | 3      | 1     |
  | `clipped`      | 0      | 1     |

  Every rule now fires. `shaky` fired on five action cam segments, all of them handheld:

  | file                            | motion | stability |
  | ------------------------------- | ------ | --------- |
  | `DJI_20250711174354_0182_D.MP4` | 0.0872 | 0.667     |
  | `DJI_20250711174429_0184_D.MP4` | 0.1093 | 0.687     |
  | `DJI_20250713135508_0196_D.MP4` | 0.0521 | 0.696     |
  | `DJI_20250714103601_0225_D.MP4` | 0.0718 | 0.671     |
  | `DJI_20250714212032_0235_D.MP4` | 0.0501 | 0.217     |

  `no_motion` drops from 3 to 1 and `clipped` rises from 0 to 1 for two reasons. The blown out night clip, `DJI_20250714212032_0235_D.MP4` at motion 0.0019 and clipping 0.548, is now reported as the exposure defect it is. And one hovering drone shot, `DJI_0756.MP4` at motion 0.0193, sits above the new floor and survives.

  An earlier version of this note claimed that two hovering shots at 0.0147 and 0.0193 both survive. That is wrong: 0.015 is the floor, so `DJI_0779.MP4` at 0.0147 falls below it and is the single remaining `no_motion` rejection. Of the six segments under the floor, two are `too_short` before the motion rule runs, two more are `too_short` at 0.0000, one is the `clipped` night shot, and `DJI_0779.MP4` is the one the rule is actually there to catch.

  Top twelve by score, class of each: drone, drone, actioncam, actioncam, drone, actioncam, actioncam, actioncam, actioncam, phone, actioncam, actioncam. That is **3 drone, 8 actioncam, 1 phone**, so no class holds all twelve. Before this change the same list was ten proxy sourced action cam segments and two drone, with the best drone segment at rank 2; the drone now takes ranks 1 and 2 and the phone reaches rank 10 from a class of four candidates.

- [x] 4.2 Update `SPEC.md` section 7.3 (rule order, shaky definition, exposure weight) and `autocut.example.toml`. Verify prettier passes on the Markdown.
- [x] 4.3 Run `make lint` and `make docker-test`, commit on branch `feat/m2-scoring-tuning` following `sf-commit-convention`, open a pull request.

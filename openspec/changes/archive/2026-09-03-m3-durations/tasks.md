## 1. Config and schema

- [x] 1.1 Add to `SelectionConfig` in `autocut/core/config.py`: `duration_by_class`, `duration_min_seconds`, `duration_max_seconds`, `score_duration_range`, `hero_share`, `hero_multiplier`, `alternate_durations`, `target_total_seconds`, `snap_to_motion`, `snap_window_seconds`, with the defaults from the spec, and document them in `autocut.example.toml`. Verify with config default tests.
- [x] 1.2 Add `duration_reason` and `snapped` to `Segment` and `total_duration_s` to the manifest selection block. Verify with the manifest round trip test.

## 2. Durations

- [x] 2.1 Add `autocut/core/durations.py` with `assign_durations(selected, manifest, config, override) -> None` implementing base by class, score scaling, hero bonus, alternation, total target and clamps, writing `target_duration_s` and `duration_reason`. Verify with unit tests on synthetic selections for every scenario in `specs/clip-durations/spec.md`, including the hero protection and the shortfall report.
- [x] 2.2 Call it in `select.py` after the greedy pick and before window placement; make `--duration` the uniform override. Verify with `CliRunner` tests: defaults give varied durations, `--duration 3.0` gives uniform 3.0, the summary line prints total and bucket counts.

## 3. Window

- [x] 3.1 Make `best_window` take the per-candidate duration. Verify with a unit test where two candidates get different durations and different window lengths.
- [x] 3.2 Add the motion snap in `window.py`. Verify with unit tests for the pan-begins and snap-would-cost-quality scenarios on synthetic motion and score series.

## 4. Report

- [x] 4.1 Show target duration and reason on selected cards. Verify with a report unit test.

## 5. Validation

- [x] 5.1 Run `autocut select` and `autocut export` on the real Sardinia project with defaults. Record in this task: duration distribution per class (min, median, max), the four hero clips, how many alternation and clamped reasons occurred, how many snaps happened, total edit duration, and export wall time. Then run with `--duration 3.0` to confirm the M2 behavior is reproducible.

  Linux development host, 2026-09-03, the 40 clip Sardinia selection with the shipped defaults. The selection itself is unchanged from milestone 2: 40 clips of 60 candidates, actioncam 24, drone 14, phone 2.

  **Duration per class**, in seconds:

  | class     | clips | min  | median | max  | seconds | seconds at a uniform 3.0 |
  | --------- | ----- | ---- | ------ | ---- | ------- | ------------------------ |
  | actioncam | 24    | 1.51 | 2.02   | 3.38 | 49.8    | 72.0                     |
  | drone     | 14    | 3.15 | 4.01   | 6.00 | 57.2    | 42.0                     |
  | phone     | 2     | 2.25 | 2.64   | 3.04 | 5.3     | 6.0                      |

  **Total edit duration 112.3 s**, against 120.0 s at a uniform 3.0. 34 of the 40 clips have a distinct length.

  **Reasons:** `base` 27, `alternation` 9, `hero` 4. No clip was `clamped`: every selected segment is longer than the duration its class and score asked for. No clip was scaled by `total`, since `target_total_seconds` is off by default.

  **The four heroes**, the top 10 percent by score:

  | order | class     | file                            | score | duration |
  | ----- | --------- | ------------------------------- | ----- | -------- |
  | 026   | actioncam | `DJI_20250715144108_0241_D.MP4` | 0.814 | 3.38 s   |
  | 029   | actioncam | `DJI_20250715145050_0249_D.MP4` | 0.764 | 3.32 s   |
  | 036   | drone     | `DJI_0803.MP4`                  | 0.757 | 6.00 s   |
  | 037   | drone     | `DJI_0811.MP4`                  | 0.831 | 6.00 s   |

  Both drone heroes sit on the 6.0 s maximum, which is the bound doing its job rather than a surprise, so they keep the reason `hero`.

  **Snaps:** 16 of 40 windows moved onto a motion boundary.

  **Export:** 40 clips in 198.3 s, none failed, 943 MiB (988 136 448 bytes). Every output lands within 19.7 ms of its target, well inside the 40 ms frame at 25 fps.

  **The folder grew while the edit got shorter.** 943 MiB against 741 MiB for the milestone 2 export, even though the edit lost 7.7 s. The seconds moved from the action cam, which is 1080p from a proxy-sized original, to the drone, which is 4K: drone seconds went from 42.0 to 57.2 and action cam from 72.0 to 49.8. Length in seconds and size on disk are not the same currency when the classes differ this much in resolution.

  **`--duration 3.0` reproduces milestone 2 exactly:** 40 clips, every one 3.0 s, every reason `override`, total 120.0 s, the same picks. The summary line drops the bucket counts under the override, because sorting clips against their class base and naming heroes describes nothing when every clip is the same length.

- [x] 5.2 Copy the new export next to the previous one so the user can compare both in CapCut; report the path. Update `SPEC.md` sections 7.4 and 7.6 with the duration rules and the M4 contract. Run `make lint` and `make docker-test`, commit on branch `feat/m3-durations` following `sf-commit-convention`, open a pull request.

  The new edit is at `~/Documents/autocut/edit-sardegna-durations`, beside the milestone 2 edit at `~/Documents/autocut/edit-sardegna`. Both hold 40 clips of the same shots in the same order; the difference is their lengths. 742 MiB against 944 MiB, 120.0 s against 112.3 s. It was built there rather than copied, so nothing large passed through a temporary folder.

  `SPEC.md` section 7.4 gains the snap and a Clip durations subsection covering the whole order, and section 7.6 records the contract beat sync inherits: it rounds the assigned durations to beat multiples instead of deriving them from the score, and a `hero` clip keeps the longer multiple on a tie.

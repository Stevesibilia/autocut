## 1. Config and schema

- [x] 1.1 Add `selection.place_radius_m`, `selection.place_visit_gap_seconds`, `selection.max_clips_per_place`, `selection.max_candidate_share` to `autocut/core/config.py` and `autocut.example.toml`. Verify with config default tests.
- [x] 1.2 Set every class of `export.remove_audio` to true in `autocut/core/config.py` and `autocut.example.toml`, and update the audio scenarios in `tests/unit/test_ffmpeg_cmd.py` and `tests/unit/test_export.py` to the silent-by-default and ambience-opted-in cases. Verify with those tests and the config default test.
- [x] 1.3 Add `place_id`, `visit_id`, `held_by` to `Segment` and place and visit counts to the manifest selection block. Verify with the manifest round trip test.

## 2. Places

- [x] 2.1 Add `autocut/core/places.py` with `candidate_position(segment, file, telemetry)`, `group_places(candidates, radius_m)` by single linkage with haversine distance, and `split_visits(place, gap_s)`. Verify with unit tests for the one-beach, two-coves, no-GPS, two-days and eleven-minutes scenarios, plus a chain of positions 100 m apart forming one place.

## 3. Selection

- [x] 3.1 Compute places and visits in `select.py` before the greedy loop, add the place cap to `_eligible` with the last-resort lift, record `held_by` and reason `place_cap`. Verify with unit tests for the five-shots and cap-lifted scenarios.
- [x] 3.2 Apply the candidate share ceiling to `max_clips` unless the flag was explicit, and print places, visits, held back count and ceiling in the summary line. Verify with `CliRunner` tests for the ceiling and explicit flag scenarios.

## 4. Report

- [x] 4.1 Add place and visit on cards, the held back reason with orders, the place filter and the header list. Verify with report unit tests.

## 5. Validation

- [x] 5.1 Run `autocut select` on the real Sardinia project with defaults and with `--max-clips 40`. Record in this task: number of places and visits, which places the drone clips 30 to 34 of the previous edit fall into, how many candidates the place cap held back, the selected count under the ceiling, and the class split of both runs. Export the default run to `~/Documents/autocut/edit-sardegna-places` and report the path.

  Linux development host, 2026-09-03, the 72 file Sardinia set. 60 candidates, 58 of them eligible once the two vertical phone clips are held back.

  **Places and visits: 6 and 6.** Every place was visited once, so on this footage the visit split never fires; the two hour gap is there for the holiday that returns to a beach, which this one did not. 35 of the 60 candidates have no place at all: the Action 4 writes no GPS, so every action cam clip is outside this cap entirely.

  | place | files | candidates | selected with defaults |
  | ----- | ----- | ---------- | ---------------------- |
  | 0     | 7     | 7          | 2                      |
  | 1     | 2     | 2          | 1                      |
  | 2     | 7     | 7          | 3                      |
  | 3     | 5     | 5          | 3                      |
  | 4     | 2     | 2          | 0                      |
  | 5     | 2     | 2          | 1                      |

  **The five clips that started this all fall in place 2, visit 2.** Clips 30 to 34 of the previous edit were `DJI_0772`, `DJI_0776`, `DJI_0786`, `DJI_0793` and `DJI_0800`, and the grouping puts all five in one visit. Three survive as orders 23, 24 and 25; `DJI_0776` and `DJI_0786` are now candidates with reason `place_cap` naming those three. That is the CapCut complaint answered at its cause rather than by turning the diversity penalty up.

  **Held back by the cap: 6 with defaults, 4 with `--max-clips 40`.** Four in place 2 and two in place 3 with defaults. With forty slots the cap has to be lifted for two visits, and a lifted cap holds nobody back, which is why the count falls rather than rises.

  | run              | selected | actioncam | drone | phone | held back | total   |
  | ---------------- | -------- | --------- | ----- | ----- | --------- | ------- |
  | defaults         | 29       | 19        | 9     | 1     | 6         | 77.0 s  |
  | `--max-clips 40` | 40       | 24        | 14    | 2     | 4         | 111.1 s |

  **The ceiling bound the default run to 29 slots**, half of the 58 eligible candidates rounded up, against the configured `max_clips` of 40. The CLI says so and names the flag that overrides it.

  **Export:** 29 clips in 124.6 s, none failed, 619 MiB, and **no output carries an audio stream**, against two in each previous edit. The default is now silent for every class.

- [x] 5.2 Update `SPEC.md` sections 7.4 and 7.7 (audio default). Run `make lint` and `make docker-test`, commit on branch `feat/m3-place-cap` following `sf-commit-convention`, open a pull request.

  The edit is at `~/Documents/autocut/edit-sardegna-places`, beside `edit-sardegna` from milestone 2 and `edit-sardegna-durations`. Section 7.4 gains a Places and visits subsection and the candidate share ceiling; section 7.7 records that every class is silent by default and how a class opts back in.

  One departure from the task text: `place_cap` joins `vertical` in `EXCLUSIONS` rather than the rejection reasons, because it says what this configuration does with a clip that is otherwise fine. That makes it cleared and re-decided on every run, like the vertical mark, so a looser cap undoes it.

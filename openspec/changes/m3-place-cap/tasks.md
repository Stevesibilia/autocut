## 1. Config and schema

- [ ] 1.1 Add `selection.place_radius_m`, `selection.place_visit_gap_seconds`, `selection.max_clips_per_place`, `selection.max_candidate_share` to `autocut/core/config.py` and `autocut.example.toml`. Verify with config default tests.
- [ ] 1.2 Set every class of `export.remove_audio` to true in `autocut/core/config.py` and `autocut.example.toml`, and update the audio scenarios in `tests/unit/test_ffmpeg_cmd.py` and `tests/unit/test_export.py` to the silent-by-default and ambience-opted-in cases. Verify with those tests and the config default test.
- [ ] 1.3 Add `place_id`, `visit_id`, `held_by` to `Segment` and place and visit counts to the manifest selection block. Verify with the manifest round trip test.

## 2. Places

- [ ] 2.1 Add `autocut/core/places.py` with `candidate_position(segment, file, telemetry)`, `group_places(candidates, radius_m)` by single linkage with haversine distance, and `split_visits(place, gap_s)`. Verify with unit tests for the one-beach, two-coves, no-GPS, two-days and eleven-minutes scenarios, plus a chain of positions 100 m apart forming one place.

## 3. Selection

- [ ] 3.1 Compute places and visits in `select.py` before the greedy loop, add the place cap to `_eligible` with the last-resort lift, record `held_by` and reason `place_cap`. Verify with unit tests for the five-shots and cap-lifted scenarios.
- [ ] 3.2 Apply the candidate share ceiling to `max_clips` unless the flag was explicit, and print places, visits, held back count and ceiling in the summary line. Verify with `CliRunner` tests for the ceiling and explicit flag scenarios.

## 4. Report

- [ ] 4.1 Add place and visit on cards, the held back reason with orders, the place filter and the header list. Verify with report unit tests.

## 5. Validation

- [ ] 5.1 Run `autocut select` on the real Sardinia project with defaults and with `--max-clips 40`. Record in this task: number of places and visits, which places the drone clips 30 to 34 of the previous edit fall into, how many candidates the place cap held back, the selected count under the ceiling, and the class split of both runs. Export the default run to `~/Documents/autocut/edit-sardegna-places` and report the path.
- [ ] 5.2 Update `SPEC.md` sections 7.4 and 7.7 (audio default). Run `make lint` and `make docker-test`, commit on branch `feat/m3-place-cap` following `sf-commit-convention`, open a pull request.

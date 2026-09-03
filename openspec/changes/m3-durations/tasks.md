## 1. Config and schema

- [ ] 1.1 Add to `SelectionConfig` in `autocut/core/config.py`: `duration_by_class`, `duration_min_seconds`, `duration_max_seconds`, `score_duration_range`, `hero_share`, `hero_multiplier`, `alternate_durations`, `target_total_seconds`, `snap_to_motion`, `snap_window_seconds`, with the defaults from the spec, and document them in `autocut.example.toml`. Verify with config default tests.
- [ ] 1.2 Add `duration_reason` and `snapped` to `Segment` and `total_duration_s` to the manifest selection block. Verify with the manifest round trip test.

## 2. Durations

- [ ] 2.1 Add `autocut/core/durations.py` with `assign_durations(selected, manifest, config, override) -> None` implementing base by class, score scaling, hero bonus, alternation, total target and clamps, writing `target_duration_s` and `duration_reason`. Verify with unit tests on synthetic selections for every scenario in `specs/clip-durations/spec.md`, including the hero protection and the shortfall report.
- [ ] 2.2 Call it in `select.py` after the greedy pick and before window placement; make `--duration` the uniform override. Verify with `CliRunner` tests: defaults give varied durations, `--duration 3.0` gives uniform 3.0, the summary line prints total and bucket counts.

## 3. Window

- [ ] 3.1 Make `best_window` take the per-candidate duration. Verify with a unit test where two candidates get different durations and different window lengths.
- [ ] 3.2 Add the motion snap in `window.py`. Verify with unit tests for the pan-begins and snap-would-cost-quality scenarios on synthetic motion and score series.

## 4. Report

- [ ] 4.1 Show target duration and reason on selected cards. Verify with a report unit test.

## 5. Validation

- [ ] 5.1 Run `autocut select` and `autocut export` on the real Sardinia project with defaults. Record in this task: duration distribution per class (min, median, max), the four hero clips, how many alternation and clamped reasons occurred, how many snaps happened, total edit duration, and export wall time. Then run with `--duration 3.0` to confirm the M2 behavior is reproducible.
- [ ] 5.2 Copy the new export next to the previous one so the user can compare both in CapCut; report the path. Update `SPEC.md` sections 7.4 and 7.6 with the duration rules and the M4 contract. Run `make lint` and `make docker-test`, commit on branch `feat/m3-durations` following `sf-commit-convention`, open a pull request.

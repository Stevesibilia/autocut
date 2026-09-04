## 1. Core: user decisions

- [ ] 1.1 Add `user_decision`, `user_start_s`, `user_end_s` to `Segment` and honor them in `select.py` (kept first, rejected ineligible, caps count kept), `plan_export` and `quantize_durations` (user bounds win, reason `user`). Verify with unit tests for every scenario in `specs/user-decisions/spec.md` and the pins-first scenario.
- [ ] 1.2 Add `thumbs.sprite_for_segment(manifest, segment, config)` building a strip from the cache entry with no decoding. Verify with a unit test asserting no subprocess is started and the file exists.
- [ ] 1.3 Show user decisions in the CLI report. Verify with a report unit test.

## 2. Grid and model

- [ ] 2.1 Add `widgets/thumb_grid.py` with the delegate, sorting, filters, rejected toggle and the header counts bound to state. Verify with `qtbot` tests for the place filter and header scenario.
- [ ] 2.2 Add `widgets/scrubber.py` with hover scrubbing over the sprite strip and on-demand build. Verify with a `qtbot` test moving the pointer and asserting the frame index changes and a missing strip gets built.

## 3. Decisions, preview, sliders

- [ ] 3.1 Add keep, reject, toggle, undo with `QUndoStack` and keyboard shortcuts, wired to a debounced re-select. Verify with `qtbot` tests for the reject-with-keyboard and undo scenarios.
- [ ] 3.2 Add `widgets/preview.py` with `QMediaPlayer` playback and in and out dragging snapped to the grid, sprite fallback when playback is unavailable. Verify with `qtbot` tests for bounds saving; playback itself is checked manually.
- [ ] 3.3 Add `widgets/sliders.py` with weight and diversity sliders, debounce, and the worker threshold. Verify with `qtbot` tests that a weight change re-sorts within the debounce and diversity 0 equals score ranking.

## 4. Groups and report

- [ ] 4.1 Add `widgets/groups.py` with cluster and visit stacks and the one-click swap. Verify with a `qtbot` test for the swap scenario.
- [ ] 4.2 Add Export report to the screen. Verify with a test that user-rejected clips appear so in `report.html`.

## 5. Validation

- [ ] 5.1 Screenshot every state of the Review screen on the synthetic project into `$AUTOCUT_GUI_SHOTS` for the reviewer. Run the screen on the real Sardinia project on the Linux host and record: time to open, slider latency for weights and diversity, whether hover scrubbing is smooth, whether preview plays for each class or falls back, and the outcome of keeping one clip and rejecting one then re-running `autocut select` from the CLI.
- [ ] 5.2 Update `SPEC.md` section 11 (screen 3). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-gui-review` following `sf-commit-convention`, open a pull request.

## 1. Core: user decisions

- [x] 1.1 Add `user_decision`, `user_start_s`, `user_end_s` to `Segment` and honor them in `select.py` (kept first, rejected ineligible, caps count kept), `plan_export` and `quantize_durations` (user bounds win, reason `user`). Verify with unit tests for every scenario in `specs/user-decisions/spec.md` and the pins-first scenario.

  21 tests in `tests/unit/test_user_decisions.py`, one per scenario plus the edges. Pins are **seeded into the greedy loop** rather than given a high score: a score high enough to beat every cap is a number nobody can reason about, and no score survives the diversity penalty by construction, which a pin has to. A reject is excluded through `_excluded`, so it is also out of the candidate ceiling, which is a share of what could be picked and a reject never can be.

  Hand set bounds are read through two new properties, `Segment.effective_bounds` and `effective_center`, so the trim, the searched window and the reviewer's bounds are ordered in one place and mean the same thing to durations, beat sync and export. A hand trimmed clip takes no part in the class base, the hero bonus, the alternation or the total scaling, because every one of those would move a boundary somebody set on purpose, and `--duration` does not overrule it either.

  **One reading worth a review comment:** a keep wins over a policy exclusion. A vertical clip under `vertical_strategy = "exclude"` that the reviewer pins is selected, because the spec says selection SHALL always select a keep and that rejection rules MUST NOT change a pinned decision. The card and the report still show `vertical`, so it is visible rather than silent.

- [x] 1.2 Add `thumbs.sprite_for_segment(manifest, segment, config)` building a strip from the cache entry with no decoding. Verify with a unit test asserting no subprocess is started and the file exists.

  8 tests in `tests/unit/test_sprite_on_demand.py`. The no-process test makes `subprocess.run` and `Popen` raise rather than counting calls, because a test that counts passes just as well when the count is wrong. `shot_index` moved from `analyze.py` to `cache.py` beside `thumb_index`, so the thumbnails, the strips and the embeddings keep agreeing on which cached picture belongs to a segment.

  **The design's premise was wrong and the task is narrower than written.** The design says "the cache holds every sampled frame, so a strip can be built after the fact". It does not: an entry holds the metric arrays, one thumbnail frame per shot and, only when `analysis.sprites` was on, the pre-built strips (ADR 6, `cache.ARRAY_NAMES`). So a file analysed without sprites has nothing to build a strip from, and no amount of code changes that. What `sprite_for_segment` does instead is the case that is real and useful: the global cache outlives project folders, so a cleaned or deleted `thumbs/` is rebuilt from the entry with no ffmpeg, which is what the spec scenario asks for. The GUI switches `analysis.sprites` on for the runs it starts, and a card with no strip keeps its thumbnail. Caching every frame instead would mean the same bytes as sprites plus a schema bump that invalidates every existing entry; I did not do that unasked.

- [x] 1.3 Show user decisions in the CLI report. Verify with a report unit test.

  Five tests in `tests/unit/test_report.py`. The card gains a `user kept` or `user rejected` chip, bolder than the machine's own markers because a human decision is the one thing on the card no automatic step is allowed to have changed, and a `4.0 to 6.5 s by hand` chip when the bounds were set. The Selected panel counts both.

## 2. Grid and model

- [x] 2.1 Add `widgets/thumb_grid.py` with the delegate, sorting, filters, rejected toggle and the header counts bound to state. Verify with `qtbot` tests for the place filter and header scenario.

  A `QListView` in icon mode over the shell's model with a painting delegate, because a holiday folder is hundreds of segments and hundreds of widgets is a slow grid. The proxy gained place, reason and score range filters, a rejected toggle and the two orders. The header is project wide on purpose: it answers "how long is my edit", and a number that changed with a filter would answer nothing.

  **Beyond the task:** the grid keeps the cursor on the clip it was on across the model reset that every re-selection causes. Without it the cursor jumped to the top after each keystroke, which makes the two minute keyboard review impossible; the fallback is the row, so a reviewer's place in the list survives even when the clip they were on leaves the grid.

- [x] 2.2 Add `widgets/scrubber.py` with hover scrubbing over the sprite strip and on-demand build. Verify with a `qtbot` test moving the pointer and asserting the frame index changes and a missing strip gets built.

  `SpriteStrip` slices the strip by geometry rather than by a frame count from the manifest, so a strip built with any `sprite_max_frames` works. `StripCache` remembers a missing strip as missing, so a project analysed without sprites is not asked for the same absent file on every pointer move. Tests cover a pointer walk from 0 to 1 giving frames 0 to 7, the build on first hover, the thumbnail fallback, and the pointer position becoming a fraction of the card.

## 3. Decisions, preview, sliders

- [x] 3.1 Add keep, reject, toggle, undo with `QUndoStack` and keyboard shortcuts, wired to a debounced re-select. Verify with `qtbot` tests for the reject-with-keyboard and undo scenarios.

  `DecisionCommand`, `BoundsCommand` and `SwapCommand` on the state's `QUndoStack`. Each carries the previous decision rather than a way to recompute it, because there is nothing to recompute: a decision is what a person said, and undo means saying the previous thing again. A decision re-selects immediately rather than on the debounce, since waiting a quarter of a second to watch a rejected clip leave the grid reads as a bug; only the sliders are debounced.

- [x] 3.2 Add `widgets/preview.py` with `QMediaPlayer` playback and in and out dragging snapped to the grid, sprite fallback when playback is unavailable. Verify with `qtbot` tests for bounds saving; playback itself is checked manually.

  The panel is built to be useful without a codec: the strip and the two bounds answer "is this the moment" on their own, and `QtMultimedia` is imported inside the play handler so a machine without the media stack pays neither the import nor the noise. Bounds snap to `1 / sample_fps`, stay inside the trimmed span, and a drag shorter than one sampled frame is treated as a slip and not saved. Playback on the real footage is reported in 5.1; it cannot be judged headless.

- [x] 3.3 Add `widgets/sliders.py` with weight and diversity sliders, debounce, and the worker threshold. Verify with `qtbot` tests that a weight change re-sorts within the debounce and diversity 0 equals score ranking.

  One slider per entry in the core's own `SCORED_METRICS`, so a metric the scoring learns about appears without this file changing. A weight re-scores through the new `score.rescore` and then re-selects; diversity only re-selects. A test drags twenty values and asserts exactly one selection ran, and another asserts diversity 0 gives the pure score ranking under the caps. `reset` blocks the slider signals so going back is one edit, not one per slider.

## 4. Groups and report

- [x] 4.1 Add `widgets/groups.py` with cluster and visit stacks and the one-click swap. Verify with a `qtbot` test for the swap scenario.

  Stacks from `cluster_id` and `visit_id`, groups of one left out because they are not duplicates and have nothing to swap. A click behind the pick keeps that clip and rejects the pick in one undo step; a click on the pick itself does nothing, because it is the likeliest accident on the screen and rejecting the pick in favour of itself would be a strange thing to have to undo. At most four alternatives are shown with "and N more": the row is ordered by score and a row of a dozen thumbnails is a row nobody reads.

- [x] 4.2 Add Export report to the screen. Verify with a test that user-rejected clips appear so in `report.html`.

  The button saves the manifest first and then calls the same `render_report` the CLI uses, so there is one report and it is never a second implementation. Refused while a stage runs.

## 5. Validation

- [x] 5.1 Screenshot every state of the Review screen on the synthetic project into `$AUTOCUT_GUI_SHOTS` for the reviewer. Run the screen on the real Sardinia project on the Linux host and record: time to open, slider latency for weights and diversity, whether hover scrubbing is smooth, whether preview plays for each class or falls back, and the outcome of keeping one clip and rejecting one then re-running `autocut select` from the CLI.

  Five Review states grabbed on the synthetic project (`review-grid`, `review-hover-and-preview`, `review-filtered`, `review-decisions`, `review-groups`) plus the five screens and the empty window from the shell change. Paths in the pull request body. Nothing committed, synthetic fixtures only.

  Real run against `~/Documents/autocut/test sardegna`, output in `~/Documents/autocut/edit-sardegna-m5-review`, driven offscreen through the real widgets. **No screenshots of real footage.**

  | Measurement                    | Result                                                                            |
  | ------------------------------ | --------------------------------------------------------------------------------- |
  | Analysis with sprites on, cold | 157.5 s for 72 files, 77 segments (128.6 s without sprites in M5's shell)         |
  | Cache size with sprites        | 255 MB for the folder                                                             |
  | Screen built and shown         | 80 ms warm, 148 ms cold                                                           |
  | Grid and groups                | 60 cards, 13 stacks, 29 clips selected                                            |
  | Diversity slider               | 478 to 518 ms, median 485 ms per re-selection                                     |
  | Weight slider                  | 478 to 498 ms, median 489 ms (re-score plus re-selection)                         |
  | Hover, first frame             | 12.2 ms, the strip build                                                          |
  | Hover, next 20 moves           | median 0.02 ms, worst 0.19 ms                                                     |
  | Cards with a strip             | 60 of 60, because the run had sprites on                                          |
  | Worker threshold               | Not reached: 60 candidates against a threshold of 300, so re-selection was inline |
  | Keep and reject                | The kept clip is selected, the rejected one is a candidate, both saved            |
  | Report                         | Written, and shows both as user decisions                                         |
  | Errors                         | None                                                                              |

  **Hover scrubbing is smooth**: one 12 ms build and then two hundredths of a millisecond per move, which is a slice of a decoded pixmap. The first run of this measurement found 0 strips of 60, because the project had been analysed by the CLI without sprites and, as 1.2 records, nothing can be built from such an entry; the numbers above are from a cold run with sprites on.

  **The slider latency misses the design's aspiration and meets the spec's scenario.** The design hoped for a quarter of a second; the measurement is 485 ms, and the spec's own scenario asks for "within a second". What is left is `select_clips` reading all 72 cache entries again on every run, which is the 0.46 s the design itself measured for selection. Skipping the sprite strips in that read (a new `sprites=False` on `read_entry`, which selection passes) took it from **1.5 s to 485 ms**; going below that needs selection to accept preloaded entries, which is a core change nobody asked for and which I have not made.

  **Preview playback cannot be judged here.** `QtMultimedia` is present, the player is created and `play()` is called for the drone, action cam and phone classes without raising, and the panel says what to do if nothing appears. Whether HEVC 10-bit actually decodes is a platform question, and the Mac is where it matters (design risk note).

- [x] 5.2 Update `SPEC.md` section 11 (screen 3). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-gui-review` following `sf-commit-convention`, open a pull request.

  Section 11 records what the screen does, that user decisions live in the core and why, and the measured slider latency with the reason it is what it is. Section 15 marks Project, Analysis and Review as built. The CHANGELOG carries the same.

  Gates: `make lint` clean (ruff, format, mypy strict on 65 files). `make docker-test` **1025 passed, 57 skipped**. `make docker-test-gui` **150 passed**. `make docker-test-ai` **8 passed, 9 skipped**. Both mypy invocations from the shell change still pass: excluded on the Qt free image (46 files), full in the `dev-gui` image (65 files). In the venv the whole suite is **1183 passed, 40 skipped**.

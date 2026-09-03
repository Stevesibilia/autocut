## 1. Best window

- [x] 1.1 Add `autocut/core/window.py` with `frame_scores(entry, class_norms, weights) -> np.ndarray` and `best_window(scores, timestamps, trimmed_bounds, target_s) -> tuple[float, float]` returning center and duration. Verify with unit tests for the sharp-middle, short-candidate and edge scenarios in `specs/best-window/spec.md`.
  - `frame_scores` takes the cache entry's `arrays` dict rather than the entry, so the function has no opinion about where the arrays came from and the tests build them inline. `build_class_norms` pools every frame of a class, because ranking a frame against segment means would flatten the search.
- [x] 1.2 Add config `selection.target_duration_seconds` usage and store `best_center_s` and `target_duration_s` on every candidate during select. Verify with a manifest roundtrip test.

## 2. Similarity

- [x] 2.1 Add `autocut/core/similarity.py` with the `SimilaritySignal` protocol, the four classic signals, `combined_similarity(a, b, config)` and a memoized `SimilarityMatrix`. Add `similarity.weights` and `similarity.spatial_radius_m`, `similarity.temporal_radius_s` to config. Verify with unit tests for every scenario in `specs/similarity-signals/spec.md`, using synthetic thumbnails (shifted crop of the same image versus a different image).
  - The perceptual hash is an average hash over the thumbnail array, not `imagehash.phash`. Measured on the 60 candidates of the Sardinia set it separates pairs near in time from pairs over an hour apart by 0.080 against 0.036 for `imagehash.phash`, which the design note now records. `imagehash` was declared for that hash and is now dropped from `pyproject.toml`, since nothing imports it.
- [x] 2.2 Add `assign_clusters(matrix, threshold) -> dict[str, int]` by single linkage. Verify with the three-similar-shots scenario.
  - Signature is `assign_clusters(ids, matrix, threshold)`: the matrix memoizes pairs on demand and never holds the candidate list, so the ids have to be passed in.

## 3. Selection

- [x] 3.1 Add `autocut/core/select.py` with `select_clips(manifest, cache, config, overrides) -> SelectionResult` implementing reset, class share pre-pass, greedy loop with caps, temporal gap, `lost_to`, ordering. Verify with unit tests on synthetic manifests for every scenario in `specs/clip-selection/spec.md`.
  - Signature is `select_clips(manifest, config, overrides)`. The cache is not a parameter because the entries a run needs follow from the candidates and the config, so `select_clips` reads them itself and no caller has to assemble them first.
  - A class share is a floor, so it rounds up: a fifth of nine clips reserves two slots. Reservations are capped at `max_clips` in total, otherwise two generous shares select more clips than the edit has room for.
  - The temporal gap is enforced against every already selected clip, not only the chronological neighbours. For a set the two are the same condition, and the pairwise form does not depend on the order being final.
- [x] 3.2 Extend `Segment` with `similarity_to_selected` and `lost_to`, and `Manifest` with a `selection` block (lambda, max clips, target duration, timestamp). Verify with the manifest roundtrip test.
- [x] 3.3 Implement `autocut select` with `--max-clips`, `--duration`, `--diversity` and `autocut run`. Verify with `CliRunner` tests on the synthetic folder: selected count within caps, second run with different diversity changes the set, no ffmpeg spawned (monkeypatch `subprocess.Popen` to fail).
  - The synthetic folder is too small to guarantee that a different lambda changes the set, so the CLI test asserts the second run records the new lambda and leaves the rejections untouched. That a new lambda changes the picks is measured on the real footage in `tests/integration/test_select_real.py`.

## 4. Report

- [x] 4.1 Extend the report template and `render_report` for selected styling, order badge, best window bounds, cluster and `lost_to`. Verify with the report unit tests extended for the selected and lost-duplicate scenarios.
  - The header's selected total counts the windows that will be exported, not the segments they sit in, so it reads as the length of the edit.

## 5. Validation

- [x] 5.1 Run `autocut select` on the real Sardinia manifest with defaults and with `--diversity 0`, `0.6`, `1.0`. Record in this task: selected count per class, number of clusters, how many selections changed between lambdas, and wall time. Open the report and note whether the top picks look like a plausible edit.

  Linux development host, 2026-09-03, 72 video files of the Sardinia set, shipped defaults (`max_clips` 40, `target_duration_seconds` 3.0, `diversity_lambda` 0.6, `cluster_threshold` 0.75, `min_temporal_gap_seconds` 60). Analysis produced 77 segments, 60 of them candidates: actioncam 35, drone 21, phone 4.

  | Run               | Selected | actioncam | drone | phone | Clusters | Wall time |
  | ----------------- | -------- | --------- | ----- | ----- | -------- | --------- |
  | defaults          | 40       | 23        | 13    | 4     | 45       | 0.95 s    |
  | `--diversity 0`   | 40       | 23        | 13    | 4     | 45       | 0.96 s    |
  | `--diversity 0.6` | 40       | 23        | 13    | 4     | 45       | 0.95 s    |
  | `--diversity 1.0` | 40       | 23        | 13    | 4     | 45       | 0.96 s    |

  Wall time is the whole `autocut select` command, manifest load and save included; `select_clips` itself takes 0.46 s. No ffmpeg process is started.

  Clusters over the 60 candidates: 36 singletons, 7 pairs, one of 3 and one of 7. Ten candidates record a `lost_to`, at similarities from 0.77 to 0.85.

  Selections changed between lambdas: 4 of 40 clips between 0.0 and 0.6, 2 of 40 between 0.6 and 1.0, 2 of 40 between 0.0 and 1.0. Two thirds of the candidates fit inside `max_clips` on this set, so the penalty moves a handful of clips instead of reshaping the edit. The same three runs with `--max-clips 15` change 6, 4 and 10 clips of 15, which is the control the GUI slider is meant to be. If the defaults are meant to make the slider useful on a folder this size, `max_clips` is the number to lower, not lambda.

  The report reads as an edit structurally: 40 picks from 40 distinct source files, orders 1 to 40 contiguous, every window 3.0 s for 120 s of footage in total, the shortest gap between consecutive picks 72 s against a 60 s minimum, and the picks spread over all seven shooting days in rough proportion to the candidates per day (14 of 40 on the busiest day, which holds 22 of 60 candidates). Chronological order groups the classes into runs, because each day was shot mostly on one device, and the four phone clips land at the end where they were filmed. Whether the frames themselves are the right three seconds is a judgment on the images: the report is at `report.html` in the output folder and needs the user's eyes, not the implementer's.

- [x] 5.2 Run `make lint` and `make docker-test`, commit on branch `feat/m2-select` following `sf-commit-convention`, open a pull request.

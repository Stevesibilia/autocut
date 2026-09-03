## 1. Best window

- [ ] 1.1 Add `autocut/core/window.py` with `frame_scores(entry, class_norms, weights) -> np.ndarray` and `best_window(scores, timestamps, trimmed_bounds, target_s) -> tuple[float, float]` returning center and duration. Verify with unit tests for the sharp-middle, short-candidate and edge scenarios in `specs/best-window/spec.md`.
- [ ] 1.2 Add config `selection.target_duration_seconds` usage and store `best_center_s` and `target_duration_s` on every candidate during select. Verify with a manifest roundtrip test.

## 2. Similarity

- [ ] 2.1 Add `autocut/core/similarity.py` with the `SimilaritySignal` protocol, the four classic signals, `combined_similarity(a, b, config)` and a memoized `SimilarityMatrix`. Add `similarity.weights` and `similarity.spatial_radius_m`, `similarity.temporal_radius_s` to config. Verify with unit tests for every scenario in `specs/similarity-signals/spec.md`, using synthetic thumbnails (shifted crop of the same image versus a different image).
- [ ] 2.2 Add `assign_clusters(matrix, threshold) -> dict[str, int]` by single linkage. Verify with the three-similar-shots scenario.

## 3. Selection

- [ ] 3.1 Add `autocut/core/select.py` with `select_clips(manifest, cache, config, overrides) -> SelectionResult` implementing reset, class share pre-pass, greedy loop with caps, temporal gap, `lost_to`, ordering. Verify with unit tests on synthetic manifests for every scenario in `specs/clip-selection/spec.md`.
- [ ] 3.2 Extend `Segment` with `similarity_to_selected` and `lost_to`, and `Manifest` with a `selection` block (lambda, max clips, target duration, timestamp). Verify with the manifest roundtrip test.
- [ ] 3.3 Implement `autocut select` with `--max-clips`, `--duration`, `--diversity` and `autocut run`. Verify with `CliRunner` tests on the synthetic folder: selected count within caps, second run with different diversity changes the set, no ffmpeg spawned (monkeypatch `subprocess.Popen` to fail).

## 4. Report

- [ ] 4.1 Extend the report template and `render_report` for selected styling, order badge, best window bounds, cluster and `lost_to`. Verify with the report unit tests extended for the selected and lost-duplicate scenarios.

## 5. Validation

- [ ] 5.1 Run `autocut select` on the real Sardinia manifest with defaults and with `--diversity 0`, `0.6`, `1.0`. Record in this task: selected count per class, number of clusters, how many selections changed between lambdas, and wall time. Open the report and note whether the top picks look like a plausible edit.
- [ ] 5.2 Run `make lint` and `make docker-test`, commit on branch `feat/m2-select` following `sf-commit-convention`, open a pull request.

## Context

Read on `main` at `f7959a0` (0.6.0):

- `analyze_file` (`autocut/core/analyze.py:65`) is the only place that holds every sampled frame. Frames are `uint8` RGB, shape `(N, H, W, 3)`, long side `analysis.sample_long_side` (320), at `analysis.sample_fps` (2.0) (`sampler.py:54-97`, `:190`). It runs in a spawn process pool (`analyze.py:224-230`). A cache hit returns at `:69-71` before any decode. The full frames are not cached.
- `CacheEntry` (`cache.py:41`) holds `arrays`; `ARRAY_NAMES` (`cache.py:38`) is the whitelist `read_entry` loads (`:137`). `embedding_model` is the precedent for a model id stored in the entry's JSON (`:164-166`).
- `_aggregate` (`analyze.py:407-442`) averages each array over `indices` (the frames inside the trimmed span) and builds `Metrics`. `Metrics.faces: int | None = None` exists (`manifest.py:189`).
- `SCORED_METRICS` (`score.py:34-44`) drives the composite score, the GUI sliders (`gui/widgets/sliders.py:116`) and the profile test (`tests/unit/test_gui_profiles.py:103-114`). `_composite` drops a metric for a whole class when any segment of that class has `None` (`score.py:127-130`).
- `window.METRIC_ARRAYS` (`window.py:25-31`) maps each scored metric to its cache array for the best-window search. `frame_scores` indexes it with `METRIC_ARRAYS[metric]` (`:74-78`), so every entry of `SCORED_METRICS` with a positive weight needs a key there. Issue #96 changes that lookup to `.get` for `aesthetic`; this change adds `faces` with a real array, so it is correct either way.
- `combined_similarity` (`similarity.py:275-297`) is the one pairwise function behind clusters (`assign_clusters`), the diversity penalty (`select.py:519-523`) and `lost_to` (`select.py:726-729`). `CandidateFeatures` (`similarity.py:37-49`) is built in `select._build_features` (`select.py:316-338`).
- `providers.faces: bool = False` (`config.py:606`) and `weights.faces: float = 0.0` (`config.py:114`) exist. No code reads either. `gui/profiles.py:32-35` explains why no profile sets `weights.faces` yet.
- `cv2` is 5.0.0 (`constraints.txt`: `opencv-python-headless==5.0.0.93`). `cv2.FaceDetectorYN.create(path, "", (w, h))` loads the 2026may model in the project venv. It logs `setPreferableTarget Targets are not supported by the new graph engine` to stderr once per detector. That line is harmless.
- No synthetic fixture contains a face, and lavfi cannot draw one (`scripts/make_fixtures.py`).

## Decisions

**1. YuNet, bundled.** Download `face_detection_yunet_2026may.onnx` from `https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2026may.onnx`. Check its SHA-256 is `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` and its size is 229,738 bytes. Commit it as `autocut/core/models/face_detection_yunet_2026may.onnx`, with the MIT licence text from `https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE` beside it as `autocut/core/models/YUNET-LICENSE.txt`. Add `"autocut/core/models/*"` to `artifacts` in `[tool.hatch.build.targets.wheel]`. Add a "Models" section to `THIRD_PARTY_LICENSES.md` with a row for YuNet: version `2026may`, MIT, the file, and the upstream `https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet`. Update that file's opening paragraph so it no longer says only fonts and icons are redistributed. Use the 2026may model, not 2023mar: 2026may has dynamic input dimensions, which the OpenCV 5 engine needs for any frame size other than the export size.
Rejected: MediaPipe, a new dependency with uncertain 3.14 and arm64 wheels. InsightFace, whose weights are for non-commercial use and which pulls onnxruntime. A first-run download, which the bundle makes unnecessary for 224 KB.

**2. `autocut/core/faces.py`.** A new module, core only:

```python
FACE_MODEL_ID = "yunet-2026may"
MODEL_FILENAME = "face_detection_yunet_2026may.onnx"


def model_path() -> Path: ...


def count_faces(frames: np.ndarray, config: AnalysisConfig) -> np.ndarray: ...
```

- `model_path` resolves the file with `importlib.resources.files("autocut.core").joinpath("models", MODEL_FILENAME)`, converted to a real path with `importlib.resources.as_file`. This is the same mechanism as `gui/theme/fonts.py:18`.
- `count_faces` returns a `float64` array of length `N`: the number of detections on each frame whose score is at least `analysis.face_score_threshold` and whose box height is at least `analysis.face_min_height_share × H`. It converts each frame with `cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)`, because YuNet expects BGR and the sampler gives RGB. It calls `detector.setInputSize((W, H))` once per call. `detect` returns `(retval, faces)`, and `faces` is `None` when nothing is found: that is a count of 0.
- The detector is built through `_detector(score_threshold: float, nms_threshold: float, top_k: int)`, decorated with `functools.cache`. The worker process then builds one per settings tuple and reuses it across files. `create` takes `(str(model_path()), "", (320, 320), score_threshold, nms_threshold, top_k)`. Do not call `setPreferableBackend` or `setPreferableTarget`. `_detector` is also the seam the unit tests monkeypatch.
- A detector that fails to load, or a `cv2.error` from `detect`, raises `FaceDetectionError(RuntimeError)` with the message. `analyze_file` turns it into a warning on the `FileAnalysis`. The file is still analysed and simply has no face array. It does not fail.

**3. Configuration.** Add to `AnalysisConfig` (`config.py:56-102`), each a `Field` with a description in the style of its neighbours:

- `face_score_threshold: float = 0.8` (ge 0, le 1). YuNet's own default is 0.9. At 320 px faces are small and score lower, and 0.8 is the starting point the A/B confirms or moves.
- `face_min_height_share: float = 0.06` (ge 0, le 1). This is the box height as a share of the frame height: about 11 px at 180 px, just above YuNet's 10 px floor. Faces smaller than that are strangers on a beach, not the subject.
- `face_nms_threshold: float = 0.3` and `face_top_k: int = 50` (ge 1): YuNet's defaults, exposed because every tunable lives in config.
- `face_count_percentile: float = 75.0` (ge 0, le 100): see decision 5.

`providers.faces` keeps its name and its default of `False`. Give it a description: it runs YuNet on every sampled frame during analysis, adds about a millisecond per frame, and requires a re-analysis of cached files the first time it is turned on. Add the new fields, and `faces = false` under `[providers]`, to `autocut.example.toml` with one-line comments. Regenerate `tests/fixtures/autocut_config_snapshot.json` the way `tests/unit/test_config.py` expects.

**4. Analysis and the cache.**

- `CacheEntry` gains `face_model: str | None = None`. `write_entry` writes it to the JSON; `read_entry` reads it back and applies no staleness rule of its own.
- `ARRAY_NAMES` gains `"faces"`.
- In `analyze_file`, a cached entry is a hit only if face detection is off, or if `cached.face_model == FACE_MODEL_ID` and `"faces" in cached.arrays`. Otherwise the file is sampled and analysed again. Write the check as a small helper, `_faces_current(entry, config) -> bool`. Other readers (`embed`, `describe`, `select`, `thumbs`) do not apply the check: a stale entry still serves them until analysis refreshes it.
- When `providers.faces` is on, `analyze_file` computes `count_faces(sampled.frames, config.analysis)` after `frame_metrics`, puts it in `arrays["faces"]` and sets `face_model=FACE_MODEL_ID`. When it is off, both are absent.
- Rejected: bumping `ANALYSIS_SCHEMA_VERSION`. That would re-analyse every user's whole cache even with face detection off.

**5. Segment metric.** In `_aggregate`, when `entry.arrays` has `"faces"` and face detection is on, `Metrics.faces` is `int(np.percentile(values[indices], config.analysis.face_count_percentile, method="lower"))`, or `0` when `indices` is empty. Otherwise it is `None`. `_aggregate` does not take the config today: pass `config.analysis` down from `_build_segments`, which has it. The upper quartile rather than the mean or the maximum is used because a face turned away for a moment should not drop the count, and a single false detection should not raise it.

**6. Scoring and the best window.** Append `("faces", "faces", False)` to `SCORED_METRICS` in `score.py`, and add `"faces": "faces"` to `window.METRIC_ARRAYS`. A class whose segments have no face count leaves the metric out through the existing `None` rule, so nothing changes while detection is off or the weight is 0. The GUI gets a Faces slider from `SCORED_METRICS` on its own. Check its label in `gui/widgets/sliders.py` and add a label entry if the sliders keep a label table.

**7. The deduplication guard.** Add `faces: int | None = None` to `CandidateFeatures` and fill it in `select._build_features` from `segment.metrics.faces`. Add `face_guard: bool = True` to `SimilarityConfig`, with a description. In `combined_similarity`, before the signal loop: if `config.similarity.face_guard` is on, both counts are not `None`, and they differ, return `0.0`. Write it as `_faces_differ(a, b, config) -> bool`, next to `_excluded_for_pair`. Returning 0 removes the pair from the clusters, from the diversity penalty and from `lost_to` all at once, which is what "not duplicates" means.
Rejected: a similarity cap below `cluster_threshold`. It would keep a diversity penalty between a shot of the empty beach and the same beach with the family on it, which is the pair the guard exists for. Rejected: identity recognition. The owner chose counts only.

**8. Family profile.** In `gui/profiles.py`, the family profile adds `"providers.faces": True` and `"weights.faces": 1.0`. Rewrite the comment at `:32-35`: faces are now computed, and the family profile is the one that turns them on. The profile test walks dotted paths, so `providers.faces` is checked the same way.

**9. Report.** When `segment.metrics.faces` is a positive integer, the report card shows a chip `"N face"` or `"N faces"`, placed and styled like the aesthetic chip (`report.py:118`, `:333-337`; `report.html.j2:861-863`, `.aesthetic` at `:454`). Add a `faces_label: str | None` field to `Card` and a `.faces` rule that reuses the aesthetic chip's tokens. The GUI card is not touched.

**10. ADR and docs.**

- `docs/adr/0014-face-detection-with-yunet.md` in the house format (`# 14. Face detection with YuNet`, Date 2026-09-28, Status Accepted, Context, Decision, Consequences). It covers decision 1, the bundled model, and the count-only guard, and states that it amends SPEC §8 item 6.
- `SPEC.md`:
  - §7.3: add faces to the metric description.
  - §8 item 6: YuNet, counts, percentile, weight, guard, family profile. Drop "handled as a separate rule": it is a weighted metric.
  - §9: the `faces` array and `face_model`.
  - §15 M4b: "face detection done 2026-09-28". Only the aesthetic part remains.
- `CHANGELOG.md` under `## [Unreleased]`: one `### Added` bullet ending "(issue #95, ADR 14)".
- Format every Markdown file with `sjust format-md <path>`, and every Python snippet in this design with `ruff format` (`ruff format --check .` checks Markdown code blocks).

## Not touched

- `ANALYSIS_SCHEMA_VERSION`, `MANIFEST_SCHEMA_VERSION`.
- The embedding, tagging and describe stages, and `window.frame_scores` beyond the new map entry. Issue #96 changes `frame_scores` for `aesthetic` in parallel. Do not touch that function's lookup.
- The GUI card, the settings dialog (`gui/settings.py` `EDITED_PATHS`) and doctor.
- Face identity, face boxes in the manifest or the report, any face data leaving the machine.
- The defaults of `providers.faces` (off) and `weights.faces` (0).

## Risks / Trade-offs

- **The model does not load from the installed package** (a `Path` from `importlib.resources` inside a zip). `as_file` covers that. If a test shows the wheel build leaves the file out, fix `artifacts`. Do not copy the model elsewhere at runtime.
- **YuNet finds faces in the synthetic fixtures** (testsrc2 patterns). Report the counts; do not raise the threshold to silence them. The fixtures are not ground truth, and the real-footage A/B decides.
- **Detection is much slower than about a millisecond per 320 px frame.** Measure `count_faces` on the 10-minute synthetic 1080p clip from the analysis-performance plan (`ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=30 -t 600`), at default sampling. Put the per-frame time in the hand-back. Above 5 ms per frame, report it before going on.
- **`cv2` prints the `setPreferableTarget` warning into test output or the CLI.** It goes to the process's stderr from C++. Leave it unless a test fails on it, and mention it in the hand-back.
- **The profile test or the snapshot rejects a `providers.*` path.** Report it. Do not drop the override.
- **The rebase with #96's branch conflicts in `window.py`, `score.py`, `config.py`, the snapshot, `SPEC.md` or `CHANGELOG.md`.** The architect resolves it at merge. Do not rebase onto the other branch.

## Verification for real

The architect runs the ADR 8 A/B on the Sardinia footage before merge, with face detection off and on. It checks that:

- with detection off, the selection is identical to `main`;
- with it on, clips with people carry plausible counts on a spot check of thumbnails;
- the guard separates the pairs it should;
- the per-file analysis time grows by a few percent at most.

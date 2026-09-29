## 1. Model and detector (design decisions 1 to 3), one commit

- [ ] 1.1 Download the model and check its SHA-256 and size as in decision 1. Add it and `YUNET-LICENSE.txt` under `autocut/core/models/`. Update `artifacts` in `pyproject.toml` and add the Models section to `THIRD_PARTY_LICENSES.md`.
- [ ] 1.2 `autocut/core/faces.py` (`FACE_MODEL_ID`, `model_path`, `_detector`, `count_faces`, `FaceDetectionError`) and the new `AnalysisConfig` fields. Describe `providers.faces`. Update `autocut.example.toml` and the config snapshot.
- [ ] 1.3 Tests in `tests/unit/test_faces.py`:
  - the bundled file's SHA-256 matches decision 1;
  - `count_faces` with `_detector` monkeypatched to a fake returning fixed detections: it applies the score and height filters, gives 0 for `None`, and passes BGR frames (assert the channel order the fake sees);
  - a fake that raises `cv2.error` gives `FaceDetectionError`;
  - one `ffmpeg`-marked test that runs the real detector on sampled frames of a synthetic fixture. It asserts a count array of the right length and dtype, not a count value.
- [ ] 1.4 Commit: `feat(core): bundle the yunet face detector`.

## 2. Analysis, scoring, guard, profile, report (decisions 4 to 9), one commit

- [ ] 2.1 `CacheEntry.face_model`, the `faces` array, `_faces_current` in `analyze_file`, and `Metrics.faces` in `_aggregate` with `config.analysis` passed down. Add `faces` to `SCORED_METRICS` and `METRIC_ARRAYS`. Add `CandidateFeatures.faces`, `similarity.face_guard` and `_faces_differ`. Add the family profile overrides and the rewritten comment, the report chip, and the slider label if needed.
- [ ] 2.2 Tests:
  - `test_analyze.py`: detection off gives no array, no `face_model` and `faces is None`; detection on (fake `count_faces`) stores the array and model id; a cached entry without faces is re-sampled when detection is on and reused when off; a `FaceDetectionError` becomes a warning and the file still has segments;
  - the percentile scenario from the spec (six frames of 2, two of 1, gives 2), and an empty window;
  - `test_cache.py`: `faces` and `face_model` round-trip;
  - `test_score.py`: faces ranks when weighted; a class with a `None` count leaves it out;
  - `test_window.py`: frames with faces win the window when `weights.faces > 0`;
  - `test_similarity.py`: the guard scenarios from the spec, and `face_guard = false`;
  - `test_select.py`: two near-identical candidates with counts 0 and 2 are both selected with the guard on, and one loses to the other with it off;
  - `test_gui_profiles.py` passes with the new overrides;
  - `test_report.py`: the chip for 1 and for 3 faces, and none for 0 or `None`.
- [ ] 2.3 Commit: `feat(core): score faces and keep different people apart in deduplication`.

## 3. Docs (decision 10), one commit

- [ ] 3.1 ADR 14, `SPEC.md` §7.3, §8 item 6, §9 and §15, and `CHANGELOG.md`. Run `sjust format-md` on each Markdown file.
- [ ] 3.2 Commit: `docs: record face detection with yunet`.

## 4. Gates and hand-back

- [ ] 4.1 `make lint` and `openspec validate local-face-detection --strict`.
- [ ] 4.2 Through the test runner, run `make test` and `make docker-test-gui`, and quote the counts. The profile change reaches the GUI tests.
- [ ] 4.3 The `count_faces` timing from the risks section: ms per frame at default sampling.
- [ ] 4.4 Check `python -m build --wheel` or `uv build --wheel` in the venv or the container, and that the wheel lists `autocut/core/models/face_detection_yunet_2026may.onnx`. Quote the `unzip -l` line.
- [ ] 4.5 Tick these boxes, push the branch and hand back.

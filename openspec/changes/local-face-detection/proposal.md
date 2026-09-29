## Why

Issue #95, roadmap milestone M4b. Family scenes have value that no sharpness or motion metric sees, and two frames of the same place with different people in them are not duplicates (SPEC §8 item 6). `Metrics.faces`, `weights.faces` and `providers.faces` exist since M0, but nothing fills or reads them.

## What Changes

- Analysis SHALL count faces on every sampled frame with OpenCV's YuNet detector (`cv2.FaceDetectorYN`) when `providers.faces` is on, store the counts as a per-frame cache array, and aggregate them into `Metrics.faces` per segment.
- The YuNet model (`face_detection_yunet_2026may.onnx`, MIT, 224 KB) SHALL ship inside the package. No new Python dependency: `cv2.FaceDetectorYN` is part of `opencv-python-headless`.
- `faces` SHALL be a scored metric with the weight `weights.faces` (default 0), and SHALL shape the best-window search like the other per-frame metrics.
- Two segments whose face counts are both known and differ SHALL have similarity 0, so deduplication never merges them.
- The family profile SHALL turn face detection on and give faces a weight.
- ADR 14 records the choice of YuNet over MediaPipe and InsightFace, which SPEC §8 named.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frame-analysis`: per-frame face counts and the segment face metric.
- `similarity-signals`: the face-count guard.

## Impact

`autocut/core/faces.py` (new), `autocut/core/models/` (new, bundled model), `analyze.py`, `cache.py`, `score.py`, `window.py`, `similarity.py`, `select.py`, `report.py` and its template, `config.py`, `gui/profiles.py`, `pyproject.toml` (wheel artifacts only, no dependency change), `autocut.example.toml`, `tests/fixtures/autocut_config_snapshot.json`, tests, `SPEC.md`, `CHANGELOG.md`, `THIRD_PARTY_LICENSES.md`, `docs/adr/0014-face-detection-with-yunet.md`. No manifest schema change: `Metrics.faces` already exists. No `ANALYSIS_SCHEMA_VERSION` change: an entry without face counts is recomputed only when face detection is on.

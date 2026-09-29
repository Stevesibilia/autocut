# 14. Face detection with YuNet

Date: 2026-09-28

## Status

Accepted. Amends SPEC §8 item 6, which named MediaPipe or InsightFace.

## Context

Family scenes have value that no sharpness or motion metric sees, and two frames of the same place with different people in them are not duplicates. `Metrics.faces`, `weights.faces` and `providers.faces` have existed since M0 without anything filling or reading them (issue #95).

SPEC §8 item 6 named MediaPipe or InsightFace. MediaPipe is a new dependency with uncertain wheels for Python 3.14 and macOS arm64. InsightFace ships weights for non-commercial use only and pulls onnxruntime. OpenCV, already a dependency, ships `cv2.FaceDetectorYN`, which runs the small YuNet model (MIT) on the CPU.

## Decision

Analysis counts faces on every sampled frame with YuNet when `providers.faces` is on. The model file, `face_detection_yunet_2026may.onnx` at 224 KB, is bundled in `autocut/core/models/` with its licence, so there is no first-run download and no new Python dependency. The 2026may export is used because it has dynamic input dimensions, which the OpenCV 5 engine needs for any frame size other than the export size.

Only counts are kept, never identity. A segment's `Metrics.faces` is the 75th percentile of its per-frame counts, so a face turned away for a moment does not lower it and one false detection does not raise it. `faces` is a scored metric weighted by `weights.faces`, default 0, and takes part in the best-window search. The family profile turns detection on and weights it.

Two segments whose counts are both known and differ have similarity 0 (`similarity.face_guard`, default on). Returning 0 removes the pair from clusters, from the diversity penalty and from the record of what a clip lost to, all at once.

A cache entry records the model id. It is stale only when detection is on and the entry lacks counts from the current model, and then only analysis refreshes it. `ANALYSIS_SCHEMA_VERSION` does not change, so turning detection off costs nobody a re-analysis.

## Consequences

Detection adds about a millisecond per sampled frame, and the first analysis after turning it on re-samples cached files. The bundled model adds 224 KB to the wheel and a Models section to `THIRD_PARTY_LICENSES.md`. Counts tell a beach with the family on it from an empty one, but nothing tells one person from another. A model change means a new id and a re-analysis. Face data never leaves the machine.

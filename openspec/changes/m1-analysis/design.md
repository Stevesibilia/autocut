## Context

Ingest (change `m1-ingest`) delivers a manifest with probed files, proxies, telemetry summaries and cache keys. This change adds everything between the file list and a scored segment list. Constraints come from SPEC.md section 7.2, 7.3 and 12 and from ADR 2 (ffmpeg pipe decoding) and ADR 6 (global cache). The Sardinia test set has 4K H.264 at 25 fps, 1080p 10-bit HEVC at 50 fps with 720p proxies, and 1080p H.264 phone clips.

## Goals / Non-Goals

**Goals:**

- One decoding pass per file yields frames for both shot detection and metrics.
- Metrics are pure NumPy and OpenCV functions on `uint8` RGB arrays, testable on synthetic images without video.
- Cache read and write is a single module with a stable on-disk layout.
- Analysis of the current Sardinia folder (about 90 files) completes on the Linux box in a measured time recorded in the tasks.

**Non-Goals:**

- Selection, best window search, deduplication (M2).
- Embeddings, tags, cloud calls (M3).
- Report rendering (change `m1-report`).

## Decisions

**Sampler command.** `ffmpeg -hwaccel auto -i <file> -vf fps=<rate>,scale='if(gt(iw,ih),<long>,-2)':'if(gt(iw,ih),-2,<long>)' -f rawvideo -pix_fmt rgb24 -` with rotation applied by ffmpeg's autorotate (default on). The frame size is derived from the probe (rotation aware) so fixed size reads from the pipe are possible. On a non-zero exit with `-hwaccel auto` the sampler retries once without the flag. Alternatives: PyAV (rejected in ADR 2), OpenCV `VideoCapture` (no hardware control, rotation inconsistent).

**Shot detection on sampled frames.** Content based detection runs on the 2 fps 320 px frames already in memory using a frame difference threshold with a minimum scene length, mirroring PySceneDetect's `ContentDetector` behavior. PySceneDetect itself decodes video internally and would double the decode cost; it stays available behind `analysis.detector = "pyscenedetect"` for validation, default is the in-memory detector. Boundary precision is limited to the sample period (0.5 s), acceptable for candidates that are later windowed.

**Metric definitions.**

- Sharpness: `cv2.Laplacian(gray, CV_64F).var()` on the full frame, or on the central 60 percent crop for `actioncam`.
- Clipping: fraction of luminance pixels at 0 or 255.
- Motion: mean absolute difference between consecutive gray frames divided by 255.
- Stability: `1 - clip(std(motion over 5 frame window) / mean(motion), 0, 1)`, undefined windows get 1.
- Colorfulness: Hasler and Süsstrunk `sqrt(std_rg^2 + std_yb^2) + 0.3 * sqrt(mean_rg^2 + mean_yb^2)` on RGB.

**Telemetry driven split.** Measuring the Sardinia set showed the low altitude rule could never fire as specified. Four of the twenty-four drone clips contain a takeoff (heights from 0.6 to 2.9 metres over the first three to six seconds), but a takeoff is not a separate shot: the camera runs continuously from the ground into the cruise, and the frame to frame content difference across those clips peaks at 0.03 to 0.12, far below any usable cut threshold. Shot detection therefore returns one span per file, and the rule, which looks at the maximum height over a segment, sees 11 to 30 metres and keeps it.

So each shot is split at the points where height crosses `rules.drone.min_height_m`, before trimming, with boundaries taken from telemetry sample times snapped to the frame sampling grid. The parts that stay below become their own segments and are rejected by the unchanged rule; the parts above are untouched. Height lookup for a segment uses a half open window so a boundary sample belongs to the span starting there, otherwise the first cruise sample would rescue the takeoff it was just split away from.

Alternatives considered. Rejecting a segment on its minimum height instead of its maximum would have caught the four takeoffs without any new machinery, but it contradicts the wording of the requirement and its cruise scenario, and it throws away the whole flight whenever the drone dips once, so a deliberate low pass over a beach, often the best material, would be lost. Moving the trimmed start past the last low sample instead of splitting would keep the cruise and cost nothing, but it silently discards footage the user might want to see rejected, and it produces no card in the report explaining what happened. Leaving the rule unable to fire on real footage was the third option and was rejected outright: altitude is the most reliable signal available for discarding takeoff and landing, and a rule that cannot fire on the material it was written for is not a rule.

**Normalization and score.** Per metric, values are rank normalized across all segments in the run to 0 to 1 (clipping and motion inverted where lower is better: clipping always, motion only for the `no_motion` and `shaky` rules, not for scoring). Score is the weighted mean with weights from config. Rank normalization avoids outliers dominating and makes the diversity slider in the GUI behave predictably.

**Cache layout.** `<cache_dir>/v<schema>/<key>_<fps>_<long>.npz` for arrays plus `<same>.json` for probe, telemetry samples, segment bounds and frame source. `numpy.savez_compressed` keeps entries small. Writes go to a temp file then rename. `platformdirs.user_cache_dir("autocut")` picks the directory.

**Orchestration.** `analyze.py` exposes `analyze_files(manifest, config, progress)`: for each file, look up the cache, else sample, detect shots, compute metrics, write the entry; then trim, build segments, apply rules, normalize, score, write thumbnails and update the manifest. Files run in a process pool; the parent does normalization and scoring after all files complete because normalization is project wide. The manifest is saved after ingest and after analysis.

**Cancellation.** The progress callback may raise `AnalysisCancelled`. The orchestrator catches it between files, cancels pending futures, saves the manifest and re-raises for the CLI to report.

**Thumbnails.** Pillow writes JPEG quality 85 at the sampled 320 px size into `<out>/thumbs/<segment_id>.jpg`. Sprites concatenate all frames of the segment horizontally, capped at 60 frames.

## Risks / Trade-offs

- [2 fps seeks on long GOP HEVC decode nearly every frame anyway] → measure on the Action 4 originals versus their LRF proxies; proxies are the real lever and are on by default.
- [Rank normalization makes scores incomparable across projects] → acceptable, scores are only used to rank within one manifest; the report shows raw metrics too.
- [Altitude splits depend on telemetry sample density; at 1 Hz a boundary can be up to one second late] → boundaries snap to the frame sampling grid and the trim margins absorb the rest; revisit only if takeoff frames survive into selected clips
- [In-memory shot detector misses cuts shorter than the sample period] → document, offer the PySceneDetect path for validation.
- [Hardware decode through `-hwaccel auto` picks VAAPI in Docker without `/dev/dri`] → compose passes `/dev/dri`; the retry without the flag covers the rest.
- [Process pool memory with 4K frames] → frames are 320 px, about 200 KB each, a 5 minute file at 2 fps is 120 MB per worker at most; cap workers at physical cores.

## Open Questions

None that change the specs. The exact rejection thresholds are placeholders in config and will be tuned on real footage after this change lands.

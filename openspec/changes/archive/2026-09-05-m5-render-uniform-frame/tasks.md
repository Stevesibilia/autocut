## 1. Common frame in the planner

- [x] 1.1 Add `export.uniform_frame` (default false) to `ExportConfig`, `uniform_frame` to `ExportOverrides`, and `frame_width`/`frame_height` to the manifest `ExportInfo`. Update `autocut.example.toml`.
- [x] 1.2 Add `common_frame(manifest, config, overrides)` in `ffmpeg_cmd.py` beside `dominant_fps`: smallest fitted size by height then width over the selected clips that reach export, even dimensions, never larger than the recorded frame. Tests: 4K plus 1080 gives 1920x1080; a 720p clip gives 1280x720; excluded vertical clips do not count; a recorded 1920x1080 frame stays when the 1080 clip is rejected.
- [x] 1.3 Make `plan_export` scale to fit the frame and pad to it, with `frame_w`/`frame_h` on `ExportPlan` and the pad emitted by `filter_chain` after the vertical filters; vertical geometry takes the frame as canvas when it is on. Tests on the argument list: 4K into 1920x1080 has a scale and no pad; 1440x1080 into 1920x1080 has no scale and a centred pad; 1080x1920 `blur_pad` into 1920x1080 yields exactly the frame; with the frame off every existing export test is unchanged.
- [x] 1.4 Record the frame on the manifest at the end of a uniform export; the export fingerprint covers scale and pad so only changed clips re-encode. Test that turning the frame on re-encodes the 4K clips and skips the 1080 ones.

## 2. Render

- [x] 2.1 `render_edit` passes `uniform_frame=True` through the overrides to `export_is_current` and `export_clips`, and refuses fast mode before exporting with a message naming `export.mode = "precise"`. Test on the mixed-size synthetic project: the render succeeds with the default maximum and the file is 1920x1080; a fast mode project exports nothing and errors.
- [x] 2.2 Rewrite the uniformity refusal message as a safety net message (it should no longer name the maximum as the remedy).

## 3. Surface and docs

- [x] 3.1 `autocut export --uniform-frame`; the Export screen shows the frame under the render toggle when the export ran uniform; the report header names it.
- [x] 3.2 SPEC.md section 7 (resolution) and 7.7 (render), README, CHANGELOG. Fix the design premise sentence in `openspec/changes/m5-final-render/design.md` if it is not yet archived, otherwise leave the archive alone.
- [ ] 3.3 Gates: `make lint`, `make docker-test`, `dev-gui`. Validate on `~/Documents/autocut/edit-m5-final-render` with `export.max_width` back at the default: the render must produce a 1920x1080 file without editing the config, re-encoding only the 9 drone clips. Report the timings in the PR.

  **Validation on the real footage.** On `~/Documents/autocut/edit-m5-final-render` with `export.max_width` and `max_height` back at the defaults (3840x2160), synced to `Soundtrack test 1 (1).mp3`. A plain export first wrote the 29 clips as they were, 9 drone clips at 3840x2160 beside 20 at 1920x1080, in 121 s. `autocut render` then re-exported **9 clips and skipped 20**, exactly the clips whose size changed, and produced `montage.mp4` at **1920x1080, 73.36 s, 181 MB, in 32.7 s total**, with no edit to `autocut.toml`. Every clip in `_selects/` is 1920x1080, the manifest records a 1920x1080 frame, the report header says "Every clip on one 1920x1080 frame", and VLC plays the file and exits 0. The file is byte-for-byte the size of the one the hand-capped export produced before this change, which is the point: the frame does by itself what the user had to work out.

  **The frame rule needed one correction against the change's own examples.** "The smallest of the fitted sizes by height, then width" taken literally makes a 1440x1080 clip the frame and puts bars down the side of every 16:9 clip, which contradicts both the 1440x1080 task example and the design's "letterboxing for odd aspects is black bars in a 16:9 render". The implemented rule is: the height is the smallest fitted height, and the width is the widest clip at that height. A test pins it.

  **Center crop under a frame needed its own path.** Fitting a portrait clip inside a landscape frame shrinks it by height and leaves a narrow strip to crop from, so a 1080x1920 clip would have come out as a small picture in a large black frame. Under a frame the scale follows the width instead, so the crop fills the frame when the source is wide enough (2160x3840 gives exactly 1920x1080) and is padded onto it when it is not. Nothing is ever upscaled.

  Gates: `make lint` clean (ruff, format, mypy strict on 73 files). `make docker-test` **1158 passed, 61 skipped**. `make docker-test-gui` **279 passed, 1206 deselected**, twice, once with `-o faulthandler_timeout=300`.

  **On the hung container reported during this change:** the GUI suite is not hung. A run under `faulthandler_timeout=300` finished in 110.87 s with no timeout dump, and the plain gate command then finished in 110.71 s. The container that sat for hours had produced nothing after the fixtures line, and three container runs were regenerating the same bind-mounted `tests/fixtures/synthetic/` at the time, which is the one thing that run had that neither clean run did. Two suites must not share that directory concurrently.

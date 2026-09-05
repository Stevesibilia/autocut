## 1. Core

- [x] 1.1 Extract the concat and audio mux helpers from `autocut/core/montage.py` into `autocut/core/avmux.py` (concat list writing with escaping, `-dn -write_tmcd 0`, `apad` plus trim, and a new fade-out option), keep `montage.py` using them. Verify the existing montage tests still pass.
- [x] 1.2 Add `autocut/core/render.py` with `render_fingerprint`, `check_parts_uniform` (ffprobe parameters), and `render_edit(manifest, config, track, progress)` that runs export when stale, concatenates `_selects/` by stream copy, muxes the track with fade, writes to a temp name then renames, records the `render` block. Add `render.enabled`, `render.fade_out_seconds`, `render.filename` to config. Verify with `ffmpeg` marked tests on the synthetic project: duration equals the sum within one frame, one video stream, audio present with the click track and absent without, fade applied, second run writes nothing, non-uniform parts refused.

## 2. CLI and screens

- [x] 2.1 Add `autocut render <project> [--track] [--out]`. Verify with `CliRunner` tests including the export-stale path.
- [x] 2.2 Add the toggle and fade field to the Export screen, run the render after export when on, show the file in the summary with an Open button. Verify with `qtbot` tests for the render toggle scenario.
- [x] 2.3 Show the render in the report header. Verify with a report test.

## 3. Docs and validation

- [x] 3.1 Reword SPEC.md section 2 as the design says, update section 7.7 and the README usage. Verify prettier passes.
- [x] 3.2 Render the real Sardinia edit with `~/Downloads/Soundtrack test 1 (1).mp3` after a sync, record duration, size, render time and whether the file plays in the system player and imports into CapCut unchanged; do not commit the track. Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-final-render` following `sf-commit-convention`, open a pull request.

  **The design's central premise does not hold on this footage.** "Exported clips share codec, pixel format, resolution and frame rate by construction of the export planner" is false: the export downscales to `export.max_width` and `max_height` and never upscales, so the Sardinia edit came out of a precise mode export as 9 drone clips at 3840x2160 and 20 action cam and phone clips at 1920x1080. The render refused, correctly and with the mismatch named, which is the specified behaviour but leaves the user's real project with no render. The refusal message now names the actual cause and remedy rather than blaming fast mode. **This needs a decision** (see the pull request): the render could pick the smallest size in the edit and re-encode the clips that differ, the export could normalise upward to one size, or the refusal stands and the user sets the maximum by hand.

  **With `export.max_width = 1920` and `max_height = 1080` in `autocut.toml`**, on a copy of `edit-sardegna-montage` at `~/Documents/autocut/edit-m5-final-render`, synced to `Soundtrack test 1 (1).mp3` (measured 123.8 bpm, drifted against a proposed 120, 29 clips quantised from 76.0 s to 73.7 s, 19x4, 4x6, 5x8 and 1x12 beats):

  - **The file.** `montage.mp4`, 73.36 s, 181 MB, one h264 1920x1080 25 fps video stream and one aac 48 kHz stereo stream. The sum of the 29 exported clips is 73.36 s, so the join is exact rather than within a frame.
  - **Timings.** 33.1 s for the whole command when 9 clips had to be re-exported at the new maximum, **4.8 s for the join alone** over 181 MB, and 0.8 s for a second run, which writes nothing and says so.
  - **The track.** 79.7 s over a 73.4 s edit, so it is trimmed. Mean volume is -18.4 dB over the first 3 s and -23.9 dB over the last second, which is the 1.5 s fade.
  - **It plays.** VLC on this host plays it and exits 0 with nothing on stderr. **CapCut is not installed here**, so the import is unverified: it has to be checked on the Mac.
  - The report header shows the render, and `preview/` was left out of the copy so nothing from the montage preview could be mistaken for it. The track was read from `~/Downloads` and is not in the repository.

  Gates: `make lint` clean (ruff, format, mypy strict on 73 files). `make docker-test` **1131 passed, 61 skipped**. `make docker-test-gui` **278 passed, 1179 deselected**. In the venv, **1390 passed, 40 skipped** plus the 27 new render and CLI render tests run separately.

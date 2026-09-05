## 1. Core

- [ ] 1.1 Extract the concat and audio mux helpers from `autocut/core/montage.py` into `autocut/core/avmux.py` (concat list writing with escaping, `-dn -write_tmcd 0`, `apad` plus trim, and a new fade-out option), keep `montage.py` using them. Verify the existing montage tests still pass.
- [ ] 1.2 Add `autocut/core/render.py` with `render_fingerprint`, `check_parts_uniform` (ffprobe parameters), and `render_edit(manifest, config, track, progress)` that runs export when stale, concatenates `_selects/` by stream copy, muxes the track with fade, writes to a temp name then renames, records the `render` block. Add `render.enabled`, `render.fade_out_seconds`, `render.filename` to config. Verify with `ffmpeg` marked tests on the synthetic project: duration equals the sum within one frame, one video stream, audio present with the click track and absent without, fade applied, second run writes nothing, non-uniform parts refused.

## 2. CLI and screens

- [ ] 2.1 Add `autocut render <project> [--track] [--out]`. Verify with `CliRunner` tests including the export-stale path.
- [ ] 2.2 Add the toggle and fade field to the Export screen, run the render after export when on, show the file in the summary with an Open button. Verify with `qtbot` tests for the render toggle scenario.
- [ ] 2.3 Show the render in the report header. Verify with a report test.

## 3. Docs and validation

- [ ] 3.1 Reword SPEC.md section 2 as the design says, update section 7.7 and the README usage. Verify prettier passes.
- [ ] 3.2 Render the real Sardinia edit with `~/Downloads/Soundtrack test 1 (1).mp3` after a sync, record duration, size, render time and whether the file plays in the system player and imports into CapCut unchanged; do not commit the track. Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-final-render` following `sf-commit-convention`, open a pull request.

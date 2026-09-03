## 1. Command builder

- [ ] 1.1 Add `autocut/core/ffmpeg_cmd.py` with `ExportPlan` (window, target fps, size, mode, codec, filters, audio) and `build_export_command(plan, source, output) -> list[str]`. Verify with unit tests asserting the argument list for: precise drone (no audio), fast phone (audio kept), 50 fps action cam slow motion, 10-bit source to `yuv420p`, `blur_pad` vertical, `center_crop` vertical, LUT for one class only.
- [ ] 1.2 Add `plan_export(segment, file, manifest, config, overrides) -> ExportPlan` computing target fps (auto mode of selected fps), downscale-only size, slow motion ratio and source window, flags `fps_converted`. Verify with unit tests for the auto-fps and not-upscaled scenarios.

## 2. Naming and layout

- [ ] 2.1 Add `autocut/core/naming.py` with `clip_name(segment, file, order, duration, tag)` and `stale_outputs(selects_dir, expected_names)`. Verify with unit tests: example name matches the spec, 45 generated names sort into order, stale detection.

## 3. Export

- [ ] 3.1 Add `autocut/core/export.py` with `export_clips(manifest, config, progress, overrides)` running plans in a process pool, skipping by fingerprint, moving stale files, recording `exported_path`, `export_mode`, errors, and an `export` block on the manifest. Verify with an `ffmpeg` marked test on the synthetic manifest after select: every selected segment has an existing output, durations within one frame in precise mode, second run skips all.
- [ ] 3.2 Implement `--rejects` export into `_rejects/`. Verify with a test that rejected segments land there with the reason in the name.
- [ ] 3.3 Implement `autocut export` with `--no-audio`, `--fps`, `--fast`, `--rejects`. Verify with `CliRunner` tests.

## 4. Selection and report updates

- [ ] 4.1 Exclude display-vertical candidates in `select` when the strategy is `exclude`, marking reason `vertical`. Verify with a unit test using the vertical fixture probe.
- [ ] 4.2 Show exported file name and link on selected cards, and the fast-mode and fps-converted markers. Verify with report unit tests.

## 5. Validation

- [ ] 5.1 Export the real Sardinia selection in precise mode. Record in this task: clip count, wall time, output folder size, target fps chosen, number of slow motion clips, number of fps-converted clips. Import `_selects/` into CapCut on the Mac when available and note whether the order and playback are right; if the Mac is not available, note that this check is pending.
- [ ] 5.2 Update `SPEC.md` section 7.7 for anything that changed in practice. Run `make lint` and `make docker-test`, commit on branch `feat/m2-export` following `sf-commit-convention`, open a pull request.

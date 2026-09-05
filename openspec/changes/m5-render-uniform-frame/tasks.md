## 1. Common frame in the planner

- [ ] 1.1 Add `export.uniform_frame` (default false) to `ExportConfig`, `uniform_frame` to `ExportOverrides`, and `frame_width`/`frame_height` to the manifest `ExportInfo`. Update `autocut.example.toml`.
- [ ] 1.2 Add `common_frame(manifest, config, overrides)` in `ffmpeg_cmd.py` beside `dominant_fps`: smallest fitted size by height then width over the selected clips that reach export, even dimensions, never larger than the recorded frame. Tests: 4K plus 1080 gives 1920x1080; a 720p clip gives 1280x720; excluded vertical clips do not count; a recorded 1920x1080 frame stays when the 1080 clip is rejected.
- [ ] 1.3 Make `plan_export` scale to fit the frame and pad to it, with `frame_w`/`frame_h` on `ExportPlan` and the pad emitted by `filter_chain` after the vertical filters; vertical geometry takes the frame as canvas when it is on. Tests on the argument list: 4K into 1920x1080 has a scale and no pad; 1440x1080 into 1920x1080 has no scale and a centred pad; 1080x1920 `blur_pad` into 1920x1080 yields exactly the frame; with the frame off every existing export test is unchanged.
- [ ] 1.4 Record the frame on the manifest at the end of a uniform export; the export fingerprint covers scale and pad so only changed clips re-encode. Test that turning the frame on re-encodes the 4K clips and skips the 1080 ones.

## 2. Render

- [ ] 2.1 `render_edit` passes `uniform_frame=True` through the overrides to `export_is_current` and `export_clips`, and refuses fast mode before exporting with a message naming `export.mode = "precise"`. Test on the mixed-size synthetic project: the render succeeds with the default maximum and the file is 1920x1080; a fast mode project exports nothing and errors.
- [ ] 2.2 Rewrite the uniformity refusal message as a safety net message (it should no longer name the maximum as the remedy).

## 3. Surface and docs

- [ ] 3.1 `autocut export --uniform-frame`; the Export screen shows the frame under the render toggle when the export ran uniform; the report header names it.
- [ ] 3.2 SPEC.md section 7 (resolution) and 7.7 (render), README, CHANGELOG. Fix the design premise sentence in `openspec/changes/m5-final-render/design.md` if it is not yet archived, otherwise leave the archive alone.
- [ ] 3.3 Gates: `make lint`, `make docker-test`, `dev-gui`. Validate on `~/Documents/autocut/edit-m5-final-render` with `export.max_width` back at the default: the render must produce a 1920x1080 file without editing the config, re-encoding only the 9 drone clips. Report the timings in the PR.

## 1. Command builder

- [x] 1.1 Add `autocut/core/ffmpeg_cmd.py` with `ExportPlan` (window, target fps, size, mode, codec, filters, audio) and `build_export_command(plan, source, output) -> list[str]`. Verify with unit tests asserting the argument list for: precise drone (no audio), fast phone (audio kept), 50 fps action cam slow motion, 10-bit source to `yuv420p`, `blur_pad` vertical, `center_crop` vertical, LUT for one class only.
  - The source and output are fields of the plan rather than separate arguments, so a plan is the whole description of one clip and can be sent to a pool worker on its own.
  - Precise mode trims with `-frames:v`, not `-t`. A window rarely starts on a source frame boundary, and `-t` then measures against the `fps` filter's own grid: three seconds taken from 2.500 s of a 25 fps source measured 2.96, one frame short. A frame count states the same intent in the unit the output is made of and measured exactly 3.000000 s. Fast mode keeps `-t`, since a stream copy has no filter grid and its bounds are approximate by definition.
  - The seek strategy and the trim both changed from what the design first specified, and `design.md` now records the measurements that decided them.
  - Slow motion drops audio even for a class configured to keep it. The video is stretched by an integer ratio and the audio is not, so the sound would stop a third of the way through the clip.
  - `-map` is explicit. Left to itself ffmpeg muxes the DJI telemetry subtitle track into the output. The Action 4 also carries `djmd` and `dbgi` data streams, a timecode track and an embedded still image as a second video stream, so the first video stream is named rather than implied. `-dn` drops the input's data streams but the mp4 muxer then writes a timecode track of its own, and real footage outputs came back as video plus `tmcd` until the muxer was told not to with `-write_tmcd 0`.
  - `h264_vaapi` needs `-vaapi_device` before the input and a `format=nv12,hwupload` tail instead of `-pix_fmt`; verified encoding on the development host. `h264_videotoolbox` maps the configured CRF onto its own 1 to 100 quality scale and is verified in the argument list only, since it needs macOS.
- [x] 1.2 Add `plan_export(segment, file, manifest, config, overrides) -> ExportPlan` computing target fps (auto mode of selected fps), downscale-only size, slow motion ratio and source window, flags `fps_converted`. Verify with unit tests for the auto-fps and not-upscaled scenarios.
  - A LUT left unset in TOML arrives as `Path(".")`, because TOML has no null. That is truthy and would put `lut3d=file=.` in the chain and fail the clip, so an empty path is treated as unset and the example config leaves the table commented out.

## 2. Naming and layout

- [x] 2.1 Add `autocut/core/naming.py` with `clip_name(segment, file, order, duration, tag)` and `stale_outputs(selects_dir, expected_names)`. Verify with unit tests: example name matches the spec, 45 generated names sort into order, stale detection.
  - The date is the local date of the clip, so a clip filmed after midnight belongs to the night it was shot. The cost is that re-exporting in another timezone can rename a late night clip, which then reads as stale rather than lost.
  - `stale_outputs` ignores directories and dotfiles, so `_selects/_stale/` cannot sweep itself and a `.DS_Store` from a Mac is left alone.

## 3. Export

- [x] 3.1 Add `autocut/core/export.py` with `export_clips(manifest, config, progress, overrides)` running plans in a process pool, skipping by fingerprint, moving stale files, recording `exported_path`, `export_mode`, errors, and an `export` block on the manifest. Verify with an `ffmpeg` marked test on the synthetic manifest after select: every selected segment has an existing output, durations within one frame in precise mode, second run skips all.
  - A failed clip has its partial output deleted and its fingerprint cleared, so the next run retries it instead of mistaking a half written file for a finished one.
  - Only `_selects/` is swept for stale files. A `--rejects` run writes into `_rejects/` and must not be able to displace the edit.
- [x] 3.2 Implement `--rejects` export into `_rejects/`. Verify with a test that rejected segments land there with the reason in the name.
- [x] 3.3 Implement `autocut export` with `--no-audio`, `--fps`, `--fast`, `--rejects`. Verify with `CliRunner` tests.
  - `export` was removed from the list of stages that exit 2 as unimplemented.

## 4. Selection and report updates

- [x] 4.1 Exclude display-vertical candidates in `select` when the strategy is `exclude`, marking reason `vertical`. Verify with a unit test using the vertical fixture probe.
  - The mark is cleared and re-decided on every `select` run, because it says what the current export strategy does with the clip rather than that anything is wrong with it. A quality rejection is not cleared. `rules.py` separates the two: `REASONS` stays the rejection rules and `EXCLUSIONS` holds the policy marks, with `ALL_REASONS` for the report's filter.
- [x] 4.2 Show exported file name and link on selected cards, and the fast-mode and fps-converted markers. Verify with report unit tests.
  - A card excluded by policy is dimmed rather than tinted with the rejection colour, and its reason tag is neutral.

## 5. Validation

- [x] 5.1 Export the real Sardinia selection in precise mode. Record in this task: clip count, wall time, output folder size, target fps chosen, number of slow motion clips, number of fps-converted clips. Import `_selects/` into CapCut on the Mac when available and note whether the order and playback are right; if the Mac is not available, note that this check is pending.

  Linux development host, 2026-09-03, the 40 clip Sardinia selection, precise mode, shipped defaults otherwise.

  | run                                     | clips | target fps | wall time | folder size          | slow motion | fps converted |
  | --------------------------------------- | ----- | ---------- | --------- | -------------------- | ----------- | ------------- |
  | defaults                                | 40    | 25         | 182.5 s   | 741 MiB, 776 082 887 | 24          | 2             |
  | the superseded mode rule, as `--fps 50` | 40    | 50         | 241.1 s   | 763 MiB, 799 818 603 | 0           | 16            |

  Every clip exported, none failed, and a second run encoded nothing.

  **The `auto` rule changed because of this measurement.** The first rule was the mode of the frame rates among the selected clips, and on this footage the mode is 50: the selection is 24 clips at 50 fps, 14 at 25 and 2 at 30.033, because analysis reads the Action 4 through its 25 fps `.LRF` proxy while export reads the 50 fps original, so the rate that dominates by count is one the analysis stage never saw. At a 50 fps target the 24 Action 4 clips can never reach the two-to-one ratio slow motion needs, so the feature `SPEC.md` section 7.7 asks for never fired at all, and all 14 drone clips plus both phone clips were resampled upwards, which invents no detail. The second row of the table is that outcome.

  `auto` now takes the rate, among those present in the selection, that the most selected clips reach by whole-number division, lowest on a tie. That is 25, which 38 of the 40 clips arrive at by dropping whole frames, and the first row is what it produces: 24 clean half speed clips instead of none, 2 resampled instead of 16, a minute less encoding and 23 MiB less on disk.

  **The vertical exclusion changed the selection.** Three of the five Sardinia phone files are display-vertical, and with the default `exclude` strategy two of their candidates are now held back (the third was already rejected as `too_short`). The selection moves from actioncam 23, drone 13, phone 4 to actioncam 24, drone 14, phone 2, still 40 clips, and the minimum temporal gap now has to be relaxed to fill the last slots because two candidates left the pool. The m2-select numbers were measured before this rule existed and are superseded by these.

  **The output reads as an edit.** 40 files named `001_20250712_actioncam_clip_3.0s.mp4` through `040_20250725_phone_clip_3.0s.mp4`, sorting alphabetically into the chronological order, every clip 3.0 s within one frame, all 8-bit `yuv420p` at the target rate, no rotation metadata and no telemetry or data streams. Whether the frames are the right three seconds is a judgment on the images and needs the user's eyes on `report.html`.

  **Two things only the real footage caught.** Every Action 4 output carried a `tmcd` timecode track that the mp4 muxer writes from the video stream's timecode, which `-dn` does not touch; the builder now passes `-write_tmcd 0` and an output is one video stream plus audio when the class keeps it. And a container's duration is the longest of its streams, so a phone clip that keeps its audio reads 3.04 against a video stream of exactly 3.000000, because an AAC frame holds 21.3 ms and the last one is not split. The duration assertion measures the video stream.

  **The CapCut import check is pending.** It needs the Mac, which is not this host.

- [x] 5.2 Update `SPEC.md` section 7.7 for anything that changed in practice. Run `make lint` and `make docker-test`, commit on branch `feat/m2-export` following `sf-commit-convention`, open a pull request.

## Why

The final render (`m5-final-render`) joins exported clips by stream copy, which needs every clip to share codec, size, pixel format and frame rate. Frame rate and pixel format are already normalised, but the export scales down to `export.max_width` by `export.max_height` and never up, so mixed footage keeps mixed sizes: the Sardinia edit exported as 9 drone clips at 3840x2160 and 20 action cam and phone clips at 1920x1080, and the render refused. Today the only remedy is to cap the export by hand.

## What Changes

- The export gains a uniform frame mode: every selected clip is scaled to fit one common frame and padded to it, where the frame is the smallest fitted size among the selected clips, so nothing is ever upscaled. The frame is recorded on the manifest and only ever shrinks for a given project.
- A render (`autocut render`, `render.enabled`, the Export screen toggle) turns the uniform frame on for the export it runs, so the render always has clips it can join. An export without a render keeps today's behaviour unless `export.uniform_frame` is set.
- Vertical strategies compute their canvas from the common frame when it is on, so a padded or cropped vertical clip lands exactly on the frame.
- The render refuses a fast mode export before exporting anything, with a message naming `export.mode`, since stream copied sources can never be made uniform.
- The report and the Export summary name the frame.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `clip-export`: the resolution requirement gains the uniform frame mode and its interaction with vertical strategies and render.

## Impact

- `autocut/core/ffmpeg_cmd.py` (common frame, padding, vertical canvas), `autocut/core/export.py` (override, manifest record), `autocut/core/render.py` (force uniform, fast mode refusal), `autocut/core/config.py` (`export.uniform_frame`), `autocut/core/manifest.py` (`export.frame_width`, `export.frame_height`, additive), `autocut/cli/main.py`, `autocut/gui/screens/export.py`, `report.py`, SPEC section 7, README, CHANGELOG, `autocut.example.toml`.
- Clips whose scale changes get a new export fingerprint and re-encode once; the render fingerprint follows.
- The `final-render` capability is unchanged: it still joins by stream copy and still refuses clips that differ, as a safety net that should no longer fire.

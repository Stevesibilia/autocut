## Context

`m5-final-render` assumed that the export produces uniform clips by construction. Frame rate (reach based target) and pixel format (`yuv420p`) are uniform; size is not, because the export scales down to a maximum and never up, and a holiday edit mixes 4K drone footage with 1080p action cam and phone clips. The render's refusal is correct; the missing piece is an export that gives it clips it can join, without asking the user to work out the smallest size in their edit.

## Goals / Non-Goals

**Goals:**

- A render works on a mixed edit with default settings.
- No upscaling, ever. Quality of the smallest clip is the ceiling; the rest is scaled down to it.
- Users who only export for CapCut keep today's behaviour unless they opt in.
- Stable frame across re-exports of one project.

**Non-Goals:**

- Re-encoding inside the render. The export is the one encoder.
- Choosing the frame by majority or by area. The rule is the smallest fitted height.
- Mixed pixel formats or codecs. `passthrough` and fast mode stay outside the render.

## Decisions

**The export, not the render, makes clips uniform.** The render already runs the export when it is stale and already refuses non-uniform clips. Adding a second encoder to the render would duplicate `ffmpeg_cmd` and produce a second set of files. Instead `render_edit` passes `ExportOverrides(uniform_frame=True)` to `export_is_current` and `export_clips`; the fingerprint carries the scale and pad, so exactly the clips whose size changes re-encode (9 of 29 on the Sardinia edit, 33 s measured by the implementer), and the render's uniformity check becomes a safety net.

**Frame selection.** `common_frame(manifest, config) -> (w, h)` beside `dominant_fps`: for every selected clip that reaches export (vertical clips under `exclude` are skipped), take `fit_inside(display_w, display_h, max_w, max_h)`; the frame is the smallest by height, then width, made even. If `manifest.export.frame_width/height` is recorded, the frame is the smaller of the two, so a frame never grows for a project. Recorded after each uniform export. Alternative rejected: majority size, which would upscale the minority.

**Scale and pad.** With the frame on, `plan_export` scales the clip to fit inside the frame (no scale filter when it already fits) and pads to the frame with `pad=W:H:(ow-iw)/2:(oh-ih)/2` when the fitted size differs from the frame. `ExportPlan` gains `frame_w`, `frame_h`; `filter_chain` emits the pad after the vertical filters. Vertical geometry uses the frame as its canvas instead of the configured maximum when the frame is on, so `blur_pad` and `center_crop` produce exactly the frame; the pad is then a no-op.

**Fast mode.** `render_edit` checks `export.mode` (with overrides) first and returns one error naming `export.mode = "precise"` without exporting. Stream copied sources cannot be scaled.

**Configuration.** `export.uniform_frame: bool = False`. `ExportOverrides.uniform_frame: bool | None`. Manifest `ExportInfo` gains `frame_width: int | None`, `frame_height: int | None` (additive, no schema bump).

**Surface.** `autocut export --uniform-frame` flag; the Export screen shows "Clips exported at one size, 1920x1080" under the render toggle when it is on; the report header names the frame.

## Risks / Trade-offs

- **Quality ceiling is the smallest clip.** One 720p phone clip pulls the whole render to 720p. Accepted and made visible in the summary; the reviewer can reject that clip or set `export.uniform_frame` off and cap by hand.
- **Letterboxing** for odd aspects (4:3 phone) is black bars in a 16:9 render. Accepted; `blur_pad` covers vertical, and a blurred pad for every aspect is a later option.
- **Re-encode on first render** of an existing export. One time per project.

## Migration Plan

Additive manifest fields with defaults. Existing exports stay valid; the first render re-encodes the clips whose size changes.

## Open Questions

None.

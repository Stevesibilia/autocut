## Why

For a simple holiday edit the clips, their order, their beat-cut durations and the track are all decided before CapCut opens. The user asked for the option to skip that step: render the finished montage with the soundtrack straight from AutoCut. The exported clips are already uniform, so the render is a stream copy concat plus an audio mux, seconds of work. SPEC.md section 2 keeps "no editing" as a rule; this change adds one explicitly optional output and amends the non-goal to say so.

## What Changes

- `autocut render <project> [--track <file>] [--out <file>]` writes `montage.mp4` in the output folder at export quality: the `_selects/` clips in order, concatenated by stream copy, the synced track muxed and trimmed or padded to the edit length with a configurable fade out, hard cuts only.
- Export screen gains "Also render the montage with the track" (off by default) and a fade-out length; the Export summary reports the render.
- The render requires an export that matches the current selection; it runs export first when needed.
- Fingerprint on the render like the preview, so an unchanged edit does not re-render.
- SPEC.md section 2 non-goal reworded: no timeline, no transitions or titles; a hard-cut render of the edit with the track is an optional output.

## Capabilities

### New Capabilities

- `final-render`: writing the finished edit with its soundtrack as one file at export quality.

### Modified Capabilities

- `gui-export`: the render option and its summary line.

## Impact

- New module `autocut/core/render.py` reusing the concat and audio mux code from `montage.py` (shared helper extracted); CLI command; Export screen checkbox and fade field.
- Config: `render.enabled` (false), `render.fade_out_seconds` (1.5), `render.filename` (`montage.mp4`).
- Manifest: `render` block with fingerprint, path, duration.
- Depends on nothing pending; small.

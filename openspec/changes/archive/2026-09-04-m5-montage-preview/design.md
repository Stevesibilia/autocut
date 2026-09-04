## Context

The preview widget plays one clip through `QMediaPlayer` (after the fix for issue #38). Switching sources between 29 files leaves a visible gap at each cut, and the user wants to see the edit as CapCut would play it, with the music. Export already knows every clip's effective window and the target frame rate; ffmpeg's concat demuxer joins uniformly encoded segments without gaps.

## Goals / Non-Goals

**Goals:**

- Seamless playback of the whole edit with the track, before export.
- Under 30 s to build on the Sardinia project, rebuilt only when the edit changes.
- One player component shared by the Review and Soundtrack screens.

**Non-Goals:**

- Frame accurate scrubbing inside the montage.
- Replacing the single-clip preview or the sprite strip.
- Transitions or titles.

## Decisions

**One ffmpeg pass per clip, then concat.** Each clip is rendered to `preview/parts/<order>.mp4` at 360 px with `libx264 -preset ultrafast -crf 28 -g 25 -an`, from the proxy when present, using the same window computation as `plan_export`. Then a concat demuxer pass with `-c copy` joins them and optionally muxes the track (`-shortest`). Alternatives: one filter_complex graph over all inputs, rejected because 29 inputs of 4K decode at once exhaust memory and give no progress; a single re-encode of the concat, rejected as slower for no gain since parts are uniform.

**Fingerprint.** SHA-256 over the ordered list of (segment id, effective start, effective end, source path, mtime), plus target fps, height, preset and the track's path, size and mtime. Stored in `Manifest.preview`. Parts are cached by their own fingerprint so rejecting one clip re-renders only the concat, not 28 parts.

**Index.** `preview/montage.json` with cumulative starts from the parts' measured durations, so the timeline matches what ffmpeg actually produced.

**Player.** One `MontagePlayer` widget: `QVideoWidget`, transport controls, a timeline `QWidget` painting boundaries from the index, current clip resolved from `positionChanged`. Emits `clip_changed(segment_id)` for the grid highlight and accepts `seek_to_clip(order)`. Reused by the Soundtrack screen.

**Keyboard during playback.** The Review screen routes K, R, space, U to the currently playing clip when the montage has focus; a decision marks the montage stale and shows a rebuild hint but does not interrupt playback.

**Stale handling.** Old montage and parts are deleted on rebuild; export's stale sweep also removes `preview/` files whose fingerprint no longer matches.

## Risks / Trade-offs

- [Build time on a 150 file vacation with 40 clips] → parts are per clip and cached; a full rebuild of 40 parts from proxies at 360 px is well under a minute; progress per clip.
- [Track longer or shorter than the montage] → `-shortest` trims; a shorter track leaves silence at the end, shown on the timeline.
- [Concat of parts with different sample rates or pixel formats] → all parts are encoded with fixed parameters, so they match by construction; a test asserts the montage duration equals the sum of parts within one frame.

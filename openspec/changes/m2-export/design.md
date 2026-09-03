## Context

Selection (change `m2-select`) leaves `selected` segments with `best_center_s`, `target_duration_s` and `order`. Source files span three frame rates (25, 30, 50), two pixel formats (8 and 10-bit), rotation side data on phone clips, and proxies that must never be exported. SPEC.md section 7.7 and 7.8 and ADR 5 fix the requirements; this change decides the ffmpeg mechanics.

## Goals / Non-Goals

**Goals:**

- One pure function builds the whole ffmpeg argument list per clip, so the filter chain is unit tested and identical across Linux and macOS.
- Export is resumable and parallel; a 45 clip export re-runs in seconds when nothing changed.
- Outputs are uniform enough that CapCut does no conversion on import.

**Non-Goals:**

- Beat quantized durations (M4). Export uses `target_duration_s` around the center.
- Hardware encoding as default. Opt-in through `export.codec`.
- Tags in names (M3). The placeholder `clip` keeps the format stable.

## Decisions

**Seek strategy.** Input seeking (`-ss` before `-i`) to the window start minus one second, then `-ss 1` output side and `-t duration`, for accurate frame cuts without decoding the whole file. Pure output-side seeking decodes from the file start; pure input-side seeking lands on a keyframe. Alternative `-accurate_seek` alone is the default and is kept.

**Filter chain order.** `fps` (or `setpts` for slow motion, before `fps`), `scale` with `force_original_aspect_ratio=decrease` and even dimensions, vertical strategy (`crop` or a `split`/`boxblur`/`overlay` graph), `lut3d`, `lenscorrection`, `format=yuv420p`. Autorotate is on, so rotation is applied at decode and the output carries no rotation metadata.

**Slow motion.** Ratio is `round(source_fps / target_fps)` when at least 2. Source window duration is `target_duration / ratio` around the center; `setpts=ratio*PTS` then `fps=target` yields real frames at slow speed. Alternative frame interpolation (`minterpolate`) rejected: slow, artifacts, unnecessary at integer ratios.

**Target fps auto.** Mode of `fps` over selected clips, computed once per export and stored in the manifest export block, so re-runs are stable when a clip is deselected.

**Encoder defaults.** `libx264 -crf 18 -preset medium -pix_fmt yuv420p`, audio `aac 192k` when kept. Same output on both platforms; `h264_videotoolbox` and `h264_vaapi` are accepted values with their own quality flag mapping, opt-in.

**Skip logic.** A clip is skipped when the output exists and the manifest's recorded export fingerprint (source key, window, fps, resolution, mode, codec, filters) equals the current one. Fingerprint stored per segment; stale outputs are moved to `_selects/_stale/` rather than deleted so a wrong reselect costs nothing.

**Parallelism.** Process pool over clips sized on physical cores divided by two, since libx264 already uses threads. Progress events per clip from the parent.

## Risks / Trade-offs

- [`-ss` before `-i` lands one second early and relies on exact output-side trim] → tested by the duration assertion within one frame on the synthetic fixtures.
- [Blur pad graph is expensive] → only for vertical clips with that strategy, default is exclude.
- [Mode of fps flips when selection changes] → fps target stored in the manifest export block and reused until `--fps` or a fresh export block is requested.
- [CapCut treats 25 fps and 30 fps mixes badly] → every output is at the target, converted clips are flagged in the report.

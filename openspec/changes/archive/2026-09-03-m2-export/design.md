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

**Seek strategy.** A plain accurate input seek (`-ss` before `-i`) to the window start. Pure output-side seeking decodes from the file start, and input seeking used to land on a keyframe, which is why this design first specified seeking one second early and trimming that second back with `-ss 1` on the output side. That is no longer necessary: `-accurate_seek` is the default, so ffmpeg seeks to the previous keyframe and decodes forward to the requested time. Measured on a fixture whose only keyframe is at 0.0, the two forms give the same duration to the microsecond and the same first frame to within re-encode noise, so the simpler one is used.

**Trim.** Precise mode trims with `-frames:v`, not `-t duration` as this design first specified. A window rarely starts on a source frame boundary, and `-t` then measures against the `fps` filter's own grid and can stop a frame early: three seconds taken from 2.500 s of a 25 fps source measured 2.96, one frame short, where a count of 75 frames measured exactly 3.000000. A frame count states the same intent in the unit the output is made of. Fast mode keeps `-t`, because a stream copy has no filter grid to align to and its bounds are approximate by definition. When audio is kept the container can still read up to one frame long, since an AAC frame holds 21.3 ms and the last one is not split, so the video stream is the thing to measure.

**Filter chain order.** `fps` (or `setpts` for slow motion, before `fps`), `scale` with `force_original_aspect_ratio=decrease` and even dimensions, vertical strategy (`crop` or a `split`/`boxblur`/`overlay` graph), `lut3d`, `lenscorrection`, `format=yuv420p`. Autorotate is on, so rotation is applied at decode and the output carries no rotation metadata.

**Slow motion.** Ratio is `round(source_fps / target_fps)` when at least 2. Source window duration is `target_duration / ratio` around the center; `setpts=ratio*PTS` then `fps=target` yields real frames at slow speed. Alternative frame interpolation (`minterpolate`) rejected: slow, artifacts, unnecessary at integer ratios.

**Target fps auto.** Among the frame rates present in the selection, the one the most selected clips reach by whole-number division, lowest rate on a tie, computed once per export and stored in the manifest export block so re-runs are stable when a clip is deselected.

The first rule here was the mode of `fps` over the selected clips, and the Sardinia set showed why that is wrong. Analysis reads the Action 4 through its 25 fps `.LRF` proxy while export reads the 50 fps original, so the rate that dominates the edit by count is one the analysis stage never saw: 24 clips at 50, 14 at 25, 2 at 30.033, and the mode is 50. At a 50 fps target the Action 4 clips can never reach the two to one ratio slow motion needs, so that feature never fires, and every drone clip is upsampled for nothing. Measured, the mode gave 0 slow motion clips and 16 resampled; counting reach gives 25, and with it 24 slow motion clips and 2 resampled, in less time and less space.

Counting reach rather than clips asks the question that matters: how many clips can arrive at this target by dropping whole frames, which is the only conversion that invents nothing. A tie goes to the lower rate because the lower rate is the one that can be reached by more rates than it can reach.

**Encoder defaults.** `libx264 -crf 18 -preset medium -pix_fmt yuv420p`, audio `aac 192k` when kept. Same output on both platforms; `h264_videotoolbox` and `h264_vaapi` are accepted values with their own quality flag mapping, opt-in.

**Skip logic.** A clip is skipped when the output exists and the manifest's recorded export fingerprint (source key, window, fps, resolution, mode, codec, filters) equals the current one. Fingerprint stored per segment; stale outputs are moved to `_selects/_stale/` rather than deleted so a wrong reselect costs nothing.

**Parallelism.** Process pool over clips sized on physical cores divided by two, since libx264 already uses threads. Progress events per clip from the parent.

## Risks / Trade-offs

- [`-ss` before `-i` lands one second early and relies on exact output-side trim] → tested by the duration assertion within one frame on the synthetic fixtures.
- [Blur pad graph is expensive] → only for vertical clips with that strategy, default is exclude.
- [Mode of fps flips when selection changes] → fps target stored in the manifest export block and reused until `--fps` or a fresh export block is requested.
- [CapCut treats 25 fps and 30 fps mixes badly] → every output is at the target, converted clips are flagged in the report.

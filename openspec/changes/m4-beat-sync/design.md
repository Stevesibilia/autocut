## Context

Selected clips carry a target duration with a reason and a best window center (ADR 5, m3-durations). The soundtrack prompt proposes a BPM. The user generates a track and brings it back. SPEC.md section 7.6 and the m3-durations design fix the contract: quantize assigned durations to beats, do not re-derive them from score.

## Goals / Non-Goals

**Goals:**

- Frame exact beat multiples from the real track, with the human override always available.
- Keep the rhythm decisions of m3-durations; only round them.
- One command, re-runnable, no decoding of video.

**Non-Goals:**

- Cutting on individual beat positions inside the track (clips are placed back to back, so whole-beat durations suffice).
- Speed changes to hit a beat.
- Music analysis beyond BPM and beat times.

## Decisions

**Audio path.** `ffmpeg -i track -ac 1 -ar 22050 -f wav -` into librosa, so any container Suno exports works. `librosa.beat.beat_track` with `units="time"`; measured BPM stored with one decimal.

**Half and double tempo.** If the measured value is within tolerance of half or twice the proposed one, the warning names it and suggests `--bpm <proposed>`. Beat trackers halve or double dance tempos often; the user decides.

**Rounding rule.** Target duration in beats is `duration * bpm / 60`; choose the multiple from `soundtrack.beat_multiples` with the smallest distance; on a tie hero clips take the larger, others the smaller. Clamp to the trimmed span, falling back to smaller multiples. This preserves the long and short alternation because it rounds each clip independently around its assigned value.

**Final bounds.** Centered on `best_center_s`, snapped to the sampling grid, shifted inside the trimmed span when needed. Stored on the segment; export prefers them. Selection and durations leave them untouched; `sync` resets them first.

**Beat map.** Plain text: one beat time per line, then a blank line and `order  start  name` for each clip with cumulative starts. Enough to line clips up manually in CapCut if anything drifts.

**No proposed BPM.** Sync works without the soundtrack step; the comparison is skipped and said so.

## Risks / Trade-offs

- [Beat tracker off by a beat at the start] → only BPM matters for durations; positions are informational in the beat map.
- [Suno track BPM far from proposed] → warning with both numbers; the user picks with `--bpm`.
- [Rounding shortens many clips toward two beats at fast tempos] → multiples are configurable; the summary prints the distribution after sync.

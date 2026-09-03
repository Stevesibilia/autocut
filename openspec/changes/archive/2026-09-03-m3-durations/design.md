## Context

Selection stores `best_center_s` and `target_duration_s` per segment (ADR 5) and export cuts exactly that, so durations can change without touching export or naming. Today one project-wide duration is used. Per-frame motion and score series are in the cache, so window placement can be refined without decoding. Beat sync is planned for M4 and will quantize durations to beat multiples.

## Goals / Non-Goals

**Goals:**

- Durations that a human editor would recognize as rhythm, computed from data already present, in milliseconds.
- Every duration explainable by one word in the report.
- A stable interface for M4: it receives assigned durations and rounds them to beats.

**Non-Goals:**

- Cutting on beats or measuring music (M4).
- Transitions or speed ramps inside a clip.
- Per-shot content understanding beyond class and score (tags in `m3-tagging` may later refine bases per tag).

## Decisions

**Order of operations inside `select`.** Greedy selection first, on scores, as today. Then durations: base by class, score scaling, hero bonus, alternation over chronological order, optional total scaling, clamps. Then best window search at the assigned duration, then motion snap. Alternative: choose duration before selection so it can influence the pick; rejected because selection is about which shots, not how long, and a shorter clip does not make a worse shot better.

**Score scaling range 0.8 to 1.2.** Narrow on purpose: class base dominates, score nudges. A wide range would make a weak drone shot shorter than a strong action shot, inverting the class rhythm. Configurable.

**Hero share 10 percent, multiplier 1.5.** Four of forty clips at 6 s (drone) or 3 s (action cam) is the "let it breathe" moment without stalling the edit. Heroes are exempt from alternation shortening.

**Alternation rule.** Bucket by comparison to the class base rather than an absolute threshold, so a 2.0 s action clip and a 4.0 s drone clip are both "at base" and the rule looks for monotony in relative terms. Middle-of-three is scaled by 25 percent toward the other bucket; that is one pass, not iterated, to stay predictable.

**Total target.** A single scale factor keeps relative rhythm intact; clamps may leave a shortfall, which is reported rather than fixed by dropping clips, because clip count is the user's `max_clips` decision. Useful for M4: the Suno prompt needs a total length before the track exists.

**Motion snap.** Local minima of the cached motion series within 0.5 s of the window start, accept if mean score loss is at most 5 percent. Conservative by design; the window search already prefers sharp stable frames, the snap only fixes cuts that land mid-movement.

**Manifest.** `Segment.duration_reason: Literal["base","hero","alternation","total","clamped","override"] | None` and `Segment.snapped: bool`. `Manifest.selection.total_duration_s`. Schema version unchanged, fields are additive with defaults.

**M4 contract.** Beat sync will read `target_duration_s` and `duration_reason`, round to the nearest allowed beat multiple, and keep `hero` clips at the longer multiple on ties. Recorded here so the M4 change does not re-derive durations from score.

## Risks / Trade-offs

- [Class bases wrong for a different shooting style] → all in config, validation records the resulting distribution on the Sardinia edit.
- [Alternation shortens a clip below what the shot needs] → floor at `duration_min_seconds` and never below the trimmed span; heroes protected.
- [Motion snap moves the window off the best frames] → capped at 5 percent score loss and 0.5 s; can be disabled.
- [Longer clips increase total edit length beyond what the user wants] → `target_total_seconds` and the printed total make it visible; default off.

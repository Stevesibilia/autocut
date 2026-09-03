# 5. Best window center stored instead of final duration

Date: 2026-09-03

## Status

Accepted

## Context

Selection picks, for each surviving segment, the sub-window of a target duration with the highest mean score. Beat sync later wants each clip to last a whole number of beats, and the BPM is only known after the user has generated the track. The two steps depend on each other: the soundtrack prompt proposes a BPM from clip durations, and the final durations depend on the measured BPM.

Storing a fixed in and out point at selection time breaks beat sync whenever the beat multiple is longer than the selected window, because there is no material to extend into. Scoring several candidate durations per segment at selection time removes the problem but multiplies the stored data and forces a guess about the BPM range before any music exists. Storing only the segment bounds and the position of the best window keeps the choice open and costs nothing extra.

## Decision

We will store in the manifest, for each candidate, the segment bounds from scene detection and trimming, the target duration used at selection time, and the center of the highest scoring window. Beat sync computes the final duration from the measured BPM and the allowed beat multiples, centers the window on the stored center, clamps it to the segment bounds, and falls back to the next smaller multiple when the segment is too short. Export without beat sync uses the target duration around the same center.

## Consequences

Selection and beat sync are independent commands that can each be re-run without redoing the other. The manifest stays small and the selection step does not need to know anything about music.

The final clip can include frames outside the originally scored window when the beat multiple is longer than the target duration. Those frames sit inside the same segment and past the trim margins, so they are safe but not individually scored. The GUI must show the effective in and out points, not the scored window, when the user reviews a clip after sync.

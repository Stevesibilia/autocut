## Context

`m1-analysis` leaves per-frame metric arrays, shot bounds, telemetry and one thumbnail frame per segment in the global cache, and scored segments in the manifest. `m2-scoring-tuning` makes scores per class. Nothing yet chooses clips. SPEC.md section 7.4 and ADR 5 fix the approach: greedy with similarity penalty, best window center stored rather than final bounds, classic signals first with embeddings arriving in M3 as one more signal.

## Goals / Non-Goals

**Goals:**

- Selection runs in seconds from cache; the tuning loop is `select` twenty times over one `analyze`.
- Similarity is a pluggable list of signals with one interface, so M3 adds CLIP as a signal and nothing else changes.
- Every decision is explainable in the report: why a clip was chosen, why its neighbour lost.

**Non-Goals:**

- Semantic tags, category balancing, embeddings (M3).
- Beat durations (M4). The window center is stored for that purpose.
- Export (change `m2-export`).

## Decisions

**Per-frame composite for the window search.** Per-frame metrics are normalized with the same per-class ranks used for segment scores, but computed over all frames of the class, then weighted. Alternative: reuse the segment score for every frame, which makes every window equal and defeats the search.

**Signal interface.** `SimilaritySignal` protocol with `name`, `available(a, b) -> bool` and `value(a, b) -> float`. Combination is the weighted mean over available signals. Alternatives: a fixed formula, rejected because M3 must add a signal without touching selection; product of signals, rejected because one missing signal would zero the pair.

**Visual fallback.** A 64 bit perceptual hash Hamming distance on the cached thumbnail, mapped to 0 to 1 over 64 bits, averaged with a chi-square distance between 8x8x8 RGB histograms. Cheap, no decoding, good at "same scene", bad at "same subject from another angle", which is exactly the gap CLIP fills in M3.

The hash is an average hash computed on the thumbnail array, not `imagehash.phash` as this design first said. Measured on the 60 candidates of the Sardinia set, the average hash separates pairs that are near in time or from the same file (mean 0.601) from pairs more than an hour apart (mean 0.521) by 0.080, while `imagehash.phash` separates the same two groups by 0.036: on 320 px landscape thumbnails the DCT coefficients are dominated by sampling noise. The average hash also stays on the NumPy array already in memory instead of building a Pillow image per candidate. `imagehash` was declared for the hash this design first specified and is now removed from `pyproject.toml`, since nothing imports it.

**Cluster assignment.** Single linkage over combined similarity at `cluster_threshold` (default 0.75). Alternatives: k-means needs k; DBSCAN needs a density parameter that is footage dependent. Single linkage over a threshold is one number the user can move.

**Greedy loop.** Eligible set is every `candidate`. Each iteration computes `score - lambda * max_sim` for every eligible candidate against the selected set, applies caps by filtering eligibility, picks the max. Complexity is O(n^2) pair evaluations with n in the low hundreds, well under a second. Pairwise similarity is memoized in a matrix for the run.

**Class share.** Before the main loop, for each class whose share implies at least one slot, the loop runs restricted to that class until the share is met or the class runs out. Then the unrestricted loop fills the remainder. Alternative: a soft bonus per under-represented class, rejected as unexplainable.

**Temporal gap.** Enforced as an eligibility filter against the selected set, relaxed to unconstrained when no eligible candidate remains and slots are left.

**Reset semantics.** `select` clears `selected`, `order`, `lost_to`, `similarity_to_selected` and `cluster_id`, keeps `rejected`. Re-running after a config change is the whole point of the cache.

## Risks / Trade-offs

- [phash on 320 px thumbnails treats two sunsets in different bays as duplicates] → temporal and spatial signals pull them apart; CLIP in M3 fixes the rest.
- [Greedy with strong lambda picks a mediocre but different clip over a great near duplicate] → that is the documented intent; lambda default 0.6 is a starting point and is the GUI slider.
- [Thumbnail frame is one frame; a segment with a cut inside it is misrepresented] → segments come from shot detection, so a cut inside one is already a detector miss.

## Open Questions

None that change the specs. Default signal weights (visual 0.5, spatial 0.2, temporal 0.2, motion 0.1) are placeholders in config, tuned on the real footage in the validation task.

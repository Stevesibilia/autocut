## Why

The first CapCut review of the Sardinia edit found clips 30 to 34 nearly identical: five drone files shot at one spot within eleven minutes. The spatial and temporal signals fired, but the visual hash split them across three clusters, so the per-cluster cap of 2 let all five through, and with 40 slots for 60 candidates the diversity penalty could only reorder them. A cap on clips per place visit encodes the editor's rule directly, needs no model, and complements the embeddings planned next.

## What Changes

- Place visits: candidates with GPS are grouped by single linkage within `selection.place_radius_m` and, inside a place, split into visits when consecutive shots are more than `selection.place_visit_gap_seconds` apart. Candidates without GPS belong to no visit.
- Cap `selection.max_clips_per_place` (default 3) on selected clips per visit, applied as an eligibility filter like the cluster cap, lifted only when nothing else is eligible.
- Candidates held back by the cap stay `candidate` with reason `place_cap` and record which selected clips filled the place.
- Candidate share ceiling: `selection.max_candidate_share` (default 0.5) bounds `max_clips` to that share of the eligible candidates, so a small folder does not select two thirds of what survived the rules. The explicit `--max-clips` flag overrides it.
- `place_id` and `visit_id` on segments; the report shows the place on each card, offers a place filter, and lists places with their clip counts in the header.
- `autocut select` prints how many places and visits were found and how many candidates the place cap held back.

## Capabilities

### New Capabilities

- `place-grouping`: grouping candidates into places and visits from GPS and time.

### Modified Capabilities

- `clip-selection`: place cap and candidate share ceiling join the caps and quotas.
- `review-report`: place shown, place filter, places in the header.

## Impact

- New module `autocut/core/places.py`; `select.py` gains the filter and the ceiling; `report.py` and the template gain place fields.
- `autocut/core/config.py`: `selection.place_radius_m`, `selection.place_visit_gap_seconds`, `selection.max_clips_per_place`, `selection.max_candidate_share`.
- `autocut/core/manifest.py`: `Segment.place_id`, `Segment.visit_id`, `Segment.held_by` (ids of the selected clips that filled the cap); manifest selection block records place and visit counts.
- Independent of the AI changes; ordered before `m3-embeddings`. The reverse geocoding planned for the M4 soundtrack will name these places later.

## Context

The manifest now carries everything the prompt needs: per-clip target durations with reasons (m3-durations), places (m3-place-cap), tags (m3-tagging), captions and an OpenRouter client with gating and cost accounting (m3-cloud-providers). SPEC.md section 7.5 fixes the Suno format rules and the two-level approach: templates always, LLM optionally. The user's genres: upbeat folk, indie pop, rock, surf rock, country, Americana, reggae and dub, funk and disco, pop punk, cinematic ambient and post-rock, acoustic and ukulele pop, Italian and Mediterranean folk.

## Goals / Non-Goals

**Goals:**

- A valid prompt every time, from templates, in milliseconds.
- Genre choice explainable by one matched row the user can edit.
- The validator as the single gate for template and model output.

**Non-Goals:**

- Generating audio.
- Beat tracking (change `m4-beat-sync`).
- A music provider API (interface exists, no implementation).

## Decisions

**Genre rows, first match wins.** Each row: `when` (optional `tags_any`, `tags_dominant`, `class_min_share`, `energy` in low, mid, high, `time_of_day`), `genre`, `instruments` (list of adjective plus instrument), `bpm` range, `mood` words. Ordered specific to general, with the default row last. Alternative, a weighted score across rows, rejected as unexplainable; the report must be able to say "surf rock because beach and underwater at mid energy".

**Shipped rows (in order).** surf rock (beach with underwater or action cam share over 0.5, mid or high), reggae and dub (beach, low energy), pop punk (action cam over 0.6, high), funk and disco (people or food dominant, high), acoustic and ukulele pop (people or food dominant, low or mid), Italian and Mediterranean folk (city or street dominant, or place region matching a configurable list), Americana (drone over 0.5, mid), cinematic ambient and post-rock (drone over 0.5, low), country (mountain or street, mid), rock (high energy default), indie pop (mid energy default), upbeat folk (default).

**Energy curve.** Mean motion per selected clip in edit order, normalized per class rank as in scoring, smoothed with a three-clip window, split into thirds for the arc. Peak section placed in the third with the highest mean.

**BPM proposal.** Grid search over the row's range in integer steps; cost is the mean over clips of the distance from `duration * bpm / 60` to the nearest allowed beat multiple from `soundtrack.beat_multiples`. Ties resolve toward the range center.

**Structure templates.** Section skeletons per energy shape (rising, peak-middle, peak-late, flat), filled with instrument and mood modifiers from the row. Each instrument used at least twice by construction; the validator still checks.

**Variants.** Mood and instrument adjective swaps from the row's alternates, BPM and genre fixed. Three by default.

**Refinement.** Text call through the OpenRouter client with the same gating, retry and cost rules as descriptions; the model receives signals and the template prompt and returns the three blocks; validator decides. `soundtrack.refine` default true when cloud is enabled.

**Geocoding.** Nominatim reverse endpoint, one request per second, user agent `autocut/<version>`, cache JSON keyed by coordinates rounded to three decimals under `<cache>/geocode/`. Offline degrades to no names. Nominatim is OpenStreetMap infrastructure, not a paid provider; it is still gated by `places.geocode` so a fully offline run is possible.

## Risks / Trade-offs

- [Suno changes its format rules] → rules live in one validator module with the allowed section list in config.
- [Genre rows over-fit to Sardinia] → rows are data; validation records which row matched per run.
- [Refinement drifts from the rules] → validator is the gate; rejected refinements are recorded and counted.
- [Nominatim rate limits] → one request per place, cached, spaced; six places on the test set.

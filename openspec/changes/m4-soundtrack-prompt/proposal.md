## Why

The edit exists, the music does not. SPEC.md section 7.5 makes AutoCut write the Suno prompt from the selected clips so the track is built around the video instead of the other way round. Every input it needs is now in the manifest: durations, energy, tags, captions, places, time of day, class mix. This change writes the prompt, validates it against Suno's format rules, proposes the BPM that beat sync will need, and optionally polishes the wording with the hosted model already wired in M3.

## What Changes

- Signal extraction from the selected clips: total duration, energy curve over the sequence, dominant tags and captions, class mix, time of day, and place names from GPS through online reverse geocoding with an on-disk cache.
- Genre table in configuration seeded with the user's preferences: upbeat folk, indie pop, rock, surf rock, country, Americana, reggae and dub, funk and disco, pop punk, cinematic ambient and post-rock, acoustic and ukulele pop, Italian and Mediterranean folk. Each row maps a material profile to genre, instruments with adjectives and a BPM range.
- Template prompt generator: Title, Description and Structure blocks following the Suno rules in SPEC.md section 7.5, with the energy curve of the actual edit mapped onto the structure arc, and a proposed BPM chosen so the assigned clip durations fall near whole beats.
- Formal validator for both fields, applied to template and LLM output alike, with the malformed-prompt battery from SPEC.md section 14.
- 3 to 5 variants differing in mood or instrumentation, written to `suno-prompt.md`.
- Optional LLM refinement through the existing OpenRouter client, text only, sending derived signals and never frames, gated exactly like descriptions.
- `autocut soundtrack <project> [--variants N] [--bpm N] [--genre X]` and `autocut run` extended to call it.

## Capabilities

### New Capabilities

- `soundtrack-prompt`: deriving signals from the edit and generating validated Suno prompts with a proposed BPM.
- `prompt-validation`: enforcing Suno's Description and Structure format rules on any prompt.
- `place-names`: naming GPS places through reverse geocoding with a cache.

### Modified Capabilities

- `cloud-providers`: text completions join the client, with their own data minimization rule.

## Impact

- New modules under `autocut/core/`: `soundtrack/signals.py`, `soundtrack/genres.py`, `soundtrack/prompt.py`, `soundtrack/validate.py`, `soundtrack/refine.py`, `geocode.py`.
- `autocut/core/providers/openrouter.py` gains a text completion call; `providers/__init__.py` gains a `TextProvider` protocol.
- `autocut/core/config.py`: `soundtrack.genres` reshaped into rows with profile conditions, `soundtrack.refine` toggle, `soundtrack.default_profile`, `places.geocode` toggle.
- `autocut/core/manifest.py`: `Soundtrack` gains `signals`, `variants`, `chosen_variant`, `place_names`.
- Dependencies: none new; geocoding uses `httpx` against the Nominatim endpoint with the required user agent and one request per second.
- Independent of `m4-beat-sync` except for the proposed BPM, which it consumes.

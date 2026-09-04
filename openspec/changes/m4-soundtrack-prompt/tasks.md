## 1. Config and schema

- [ ] 1.1 Reshape `soundtrack.genres` in `autocut/core/config.py` into ordered rows with `when`, `genre`, `instruments`, `bpm`, `mood`, add `soundtrack.default_profile`, `soundtrack.refine`, `soundtrack.description_max_chars`, `soundtrack.allowed_sections`, `places.geocode`, and ship the twelve rows from the design in `autocut.example.toml`. Verify with config default tests and a test that every shipped row parses.
- [ ] 1.2 Extend `Soundtrack` in `autocut/core/manifest.py` with `signals`, `variants`, `chosen_variant`, `matched_row`, `refinement`, and places with `name` and `region`. Verify with the manifest round trip test.

## 2. Signals and places

- [ ] 2.1 Add `autocut/core/soundtrack/signals.py` with `derive_signals(manifest, config) -> Signals` (duration, count, energy curve, dominant tags, captions, class mix, time of day, place names). Verify with unit tests on a synthetic selected manifest for the Sardinia scenario.
- [ ] 2.2 Add `autocut/core/geocode.py` with the Nominatim client, spacing, cache and offline fallback. Verify with unit tests over a mocked transport for the six-places, cached and offline scenarios.

## 3. Prompt

- [ ] 3.1 Add `autocut/core/soundtrack/genres.py` with `match_row(signals, rows) -> Row`. Verify with unit tests for beach day, aerial afternoon and nothing matches.
- [ ] 3.2 Add `autocut/core/soundtrack/prompt.py` with `propose_bpm`, `build_prompt(signals, row, bpm, variant) -> Prompt` and the structure templates per energy shape. Verify with unit tests for peak placement, instrument coverage and the BPM scenario.
- [ ] 3.3 Add `autocut/core/soundtrack/validate.py` returning all violations with line numbers. Verify with the malformed battery from the spec plus a valid prompt.
- [ ] 3.4 Add `autocut/core/soundtrack/refine.py` using a new text call on the OpenRouter client with the same gate and cost accounting, plus the text payload audit test. Verify with unit tests over a mocked transport for accepted and rejected refinements.

## 4. CLI and output

- [ ] 4.1 Implement `autocut soundtrack` with `--variants`, `--bpm`, `--genre`, writing `suno-prompt.md`, and call it from `autocut run` after select. Verify with `CliRunner` tests including the not-selected exit and a written file with three valid variants.
- [ ] 4.2 Show the matched row, proposed BPM and a link to `suno-prompt.md` in the report header. Verify with a report unit test.

## 5. Validation

- [ ] 5.1 Run `autocut soundtrack` on the real Sardinia project. Record in this task: the matched row and why, the proposed BPM and the mean beat distance it achieves, the three variants, place names returned by geocoding, and whether refinement ran (key present) or was skipped. Paste the first variant into the task. If a key is present, record the refinement cost and whether it passed validation.
- [ ] 5.2 Update `SPEC.md` sections 7.5 and 15. Run `make lint` and `make docker-test`, commit on branch `feat/m4-soundtrack-prompt` following `sf-commit-convention`, open a pull request.

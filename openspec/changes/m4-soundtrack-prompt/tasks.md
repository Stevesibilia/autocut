## 1. Config and schema

- [x] 1.1 Reshape `soundtrack.genres` in `autocut/core/config.py` into ordered rows with `when`, `genre`, `instruments`, `bpm`, `mood`, add `soundtrack.default_profile`, `soundtrack.refine`, `soundtrack.description_max_chars`, `soundtrack.allowed_sections`, `places.geocode`, and ship the twelve rows from the design in `autocut.example.toml`. Verify with config default tests and a test that every shipped row parses.

  `GenreWhen`, `GenreRow` and the twelve rows are in `config.py` as the shipped defaults, and `autocut.example.toml` is generated from them, so the example and the code cannot drift: a test asserts the whole loaded config equals the defaults.

  Two fields joined the ones the task lists. `soundtrack.energy_bands` says where the
  energy curve turns low to mid to high, and `soundtrack.time_of_day` gives the hour
  bands, both because they are thresholds and AGENTS.md keeps thresholds in config.
  `places.min_interval_s` and `places.user_agent` are there because Nominatim's usage
  policy is a setting, not a constant.

  One defect the tests found in the shipped data: `accordion`, `mandolin`, `fiddle`,
  `banjo`, `clavinet` and `glockenspiel` had no adjective, and SPEC.md section 7.5 is
  explicit that an instrument needs one ("`sweeping strings`, not `strings`"). They are
  now `wheezing accordion`, `bright mandolin`, `sawing fiddle`, `rolling banjo`,
  `funky clavinet` and `twinkling glockenspiel`, and a test asserts it for every row and
  every alternate.

- [x] 1.2 Extend `Soundtrack` in `autocut/core/manifest.py` with `signals`, `variants`, `chosen_variant`, `matched_row`, `refinement`, and places with `name` and `region`. Verify with the manifest round trip test.

  `SoundtrackSignals`, `PromptVariant` and `PlaceInfo` are new models; `Soundtrack` gains
  the fields the task lists plus `matched_reason`, `genre`, `beat_distance` and
  `refinement_note`, which are what the report and the prompt file print.

  Places needed a home. Segments carried a `place_id` and the report derived everything
  else from them, so there was nowhere to put a name. `Manifest.places` is now a dict
  keyed by the place id as a string, filled by selection with the centroid of each
  place, and a name already fetched survives a re-selection. The model is `PlaceInfo`
  rather than `Place` because `autocut/core/places.py` already has a `Place` for the
  grouping and the two meet in the same call stack.

## 2. Signals and places

- [x] 2.1 Add `autocut/core/soundtrack/signals.py` with `derive_signals(manifest, config) -> Signals` (duration, count, energy curve, dominant tags, captions, class mix, time of day, place names). Verify with unit tests on a synthetic selected manifest for the Sardinia scenario.

  The energy curve is rank normalised before smoothing, for the reason scoring ranks: raw
  motion is not comparable between a drone cruising and an action cam on a wrist, and one
  outlier would flatten everything else into one band.

  **A defect the real footage found.** The first version counted only dominant tags, so
  `signals.tags` never contained `underwater`, which is a view group tag and never
  dominant by design. The surf rock row asks for beach dominant **and** underwater
  present, so it could not match on the real edit and the genre came out `indie pop`.
  Signals now carry two counts: the dominant tags for "what names this edit" and every
  tag a clip carries for "is underwater anywhere in it". With that, the real edit matches
  surf rock, which is the answer the spec scenario predicts.

- [x] 2.2 Add `autocut/core/geocode.py` with the Nominatim client, spacing, cache and offline fallback. Verify with unit tests over a mocked transport for the six-places, cached and offline scenarios.

  21 tests over a mocked transport, with an injected clock so the spacing is asserted
  without waiting: six places produce six requests and five one second gaps. The name is
  read from an ordered list of address keys, natural feature before settlement, because a
  holiday is spent at a beach rather than in the municipality that administers it.

## 3. Prompt

- [x] 3.1 Add `autocut/core/soundtrack/genres.py` with `match_row(signals, rows) -> Row`. Verify with unit tests for beach day, aerial afternoon and nothing matches.

  `match_row` returns the row, whether it matched and the reason in the words of its own
  conditions, so the CLI and the report can both print "surf rock, because dominant tag
  is beach, underwater present, energy mid".

- [x] 3.2 Add `autocut/core/soundtrack/prompt.py` with `propose_bpm`, `build_prompt(signals, row, bpm, variant) -> Prompt` and the structure templates per energy shape. Verify with unit tests for peak placement, instrument coverage and the BPM scenario.

  Four skeletons, and one renamed from the design: a peak in the last third **is** a
  rising edit, so "rising" and "peak-late" would be the same skeleton. The fourth is
  instead `front`, an edit that opens at its loudest and has nowhere to build to, which
  the Sardinia material actually produces.

  The generator satisfies the validator by construction, and a test proves it over all
  twelve rows, three energy bands and every variant: 180 prompts, no violations. The
  peak placement test asserts the peak section reaches into the last third rather than
  starting there, because a four tag section starting exactly at the two thirds mark
  would otherwise fail for being one tag early.

- [x] 3.3 Add `autocut/core/soundtrack/validate.py` returning all violations with line numbers. Verify with the malformed battery from the spec plus a valid prompt.

  35 tests, one rule broken per test so the validator is asserted to name the rule that
  broke rather than merely to fail.

  One ordering decision worth recording: a vocal tag is checked before the section word.
  `[soft vocals]` is both an unknown section and a vocal tag, and reporting the former
  would send the reader looking for the right section word for vocals.

- [x] 3.4 Add `autocut/core/soundtrack/refine.py` using a new text call on the OpenRouter client with the same gate and cost accounting, plus the text payload audit test. Verify with unit tests over a mocked transport for accepted and rejected refinements.

  `complete_text` joins the client and shares its retry, pricing and attempt counting with
  the vision call through a common `_post`. The `TextProvider` protocol is in
  `providers/__init__.py` beside `VisionProvider`.

  The text payload is built by allow list, `ALLOWED_SIGNAL_FIELDS`, rather than by
  excluding fields: a field added to the signals later does not travel until someone puts
  it on the list on purpose. The audit test asserts the request body against that list and
  against a list of forbidden substrings, the same way the vision payload test does.

## 4. CLI and output

- [x] 4.1 Implement `autocut soundtrack` with `--variants`, `--bpm`, `--genre`, writing `suno-prompt.md`, and call it from `autocut run` after select. Verify with `CliRunner` tests including the not-selected exit and a written file with three valid variants.

  14 tests. `--no-geocode` joined the options so a test, or a user, can keep the run
  offline without switching the setting off in a file. An unknown `--genre` exits 2 and
  prints the table, because guessing which row the user meant is worse than saying what
  there is.

  `refinement` distinguishes `off` from `skipped`: the user switching it off is not the
  same as it being on and unable to run, and the manifest and the CLI now agree on which
  happened.

- [x] 4.2 Show the matched row, proposed BPM and a link to `suno-prompt.md` in the report header. Verify with a report unit test.

  The panel also shows the mean distance from a whole beat, which is the number that says
  how much the beat sync in the next change will have to move. Places in the header are
  listed by their geocoded name and region when they have one.

## 5. Validation

- [x] 5.1 Run `autocut soundtrack` on the real Sardinia project. Record in this task: the matched row and why, the proposed BPM and the mean beat distance it achieves, the three variants, place names returned by geocoding, and whether refinement ran (key present) or was skipped. Paste the first variant into the task. If a key is present, record the refinement cost and whether it passed validation.

  Linux development host, 2026-09-04, the 29 clip Sardinia edit, 76.5 s. `autocut
soundtrack` takes 8.5 s on a cold geocode cache and under a second on a warm one.

  **Matched row: `surf rock`,** because the dominant tag is `beach` (15 of 29 clips,
  a share of 0.517), `underwater` is present (8 clips), and the energy band is mid. That
  is the spec's own beach day scenario arriving on real footage.

  **Signals:** 29 clips, 76.5 s, mid energy, peak in the **first** third so the shape is
  `front`, daytime. Tags across the edit: beach 15, underwater 8, aerial 6, food 2,
  city 1. Class mix actioncam 0.655, drone 0.310, phone 0.034. Energy by third: 0.670,
  0.336, 0.460. No captions, because no cloud key was available to write any.

  **Place names, six for six places, all in one region:**

  | place | name            | region    | segments |
  | ----- | --------------- | --------- | -------- |
  | 0     | Tancau sul Mare | Ogliastra | 7        |
  | 1     | Tancau sul Mare | Ogliastra | 2        |
  | 2     | Tortolì         | Ogliastra | 7        |
  | 3     | Orrì            | Ogliastra | 5        |
  | 4     | Tortolì         | Ogliastra | 2        |
  | 5     | Lanusè/Lanusei  | Ogliastra | 2        |

  Two pairs share a name. Places 0 and 1, and 2 and 4, are separate GPS clusters inside
  one locality, which is the grouping working as designed at a 150 m radius and the
  geocoder answering at the resolution a person would use. The prompt takes the three
  largest, so it says Tancau sul Mare, Tortolì and Orrì.

  **Proposed BPM 120, and the fit is poor: a mean of 0.705 beats off the grid.** This is
  the finding of the task. The row's range is 120 to 140 and 120 is its best point; a
  search freed to 60 to 200 only reaches 0.353 at 60. Per clip at 120: median 0.398
  beats off, worst 4.000, and **4 of 29 clips within a tenth of a beat**.

  The cause is structural rather than a bug. The per-clip durations from `m3-durations`
  give **27 distinct lengths across 29 clips**, from 1.503 s to 6.000 s, because each was
  chosen from its class, its score, a hero bonus and an alternation pass. No single BPM
  puts 27 arbitrary lengths on a grid of 2, 4 or 8 beats. The 6.0 s hero clip is the
  clearest case: at 120 it is 12 beats, and 12 is not in `beat_multiples`, so it is 4
  beats from anything legal at any BPM in any sane range.

  Two things follow, both for `m4-beat-sync` rather than for here. Varied durations and a
  beat grid are different goals, and the honest way to reconcile them is to requantise the
  durations against the measured track, which is what beat sync is for. And
  `beat_multiples` of 2, 4 and 8 has no entry a 6 s clip can reach; 12 and 16 would give
  the long end of the range somewhere to land.

  **Refinement: skipped.** `OPENROUTER_API_KEY` was not in the environment and reading the
  repository `.env` is blocked by policy, so no refinement has been measured against a
  live model. The CLI said so in one line and the manifest records
  `refinement: skipped` with the reason. The code path is covered by 16 unit tests over a
  mocked transport, including an accepted refinement, four kinds of rejection, and the
  payload audit.

  **The three variants** share genre and BPM and differ in mood and instrument, as the
  spec asks. The first, pasted whole:

  ```text
  Title
  tancau sul mare, daytime, surf rock

  Description
  surf rock, twangy reverb guitar, driving drums, sunny, 120 bpm, no vocals, instrumental

  Structure
  [sparse intro]
  [guitar intro]
  [sunny intro]
  [wide chorus]
  [drums chorus]
  [sunny chorus]
  [steady verse]
  [guitar verse]
  [sunny verse]
  [quiet break]
  [drums break]
  [sunny break]
  [fading outro]
  [guitar outro]
  [sunny outro]
  [end]
  ```

  The second reads `shimmering tremolo guitar, driving drums, carefree` and the third
  `shimmering tremolo guitar, driving drums, breezy`. The chorus sits second because the
  edit peaks in its first third, which is the arc following the footage rather than a
  generic one.

  The file is at `~/Documents/autocut/edit-sardegna-m4-prompt/suno-prompt.md`.

- [x] 5.2 Update `SPEC.md` sections 7.5 and 15. Run `make lint` and `make docker-test`, commit on branch `feat/m4-soundtrack-prompt` following `sf-commit-convention`, open a pull request.

  Section 7.5 describes the genre table, the validator's full rule list, the two levels,
  place names, and why the proposed BPM is a fit rather than a promise, with the measured
  numbers. Section 15 notes place names as part of M4.

  **One defect fixed here that belongs to `m3-embeddings`.** The `ai` suite was failing
  intermittently and taking three to four minutes, and the warnings said why: every test
  that sets `cache.dir` to its own `tmp_path` was downloading the 605 MB checkpoint into
  that directory, because `models_dir` was derived from `cache.dir`. The container tmpfs
  fell to 284 MB free and the download that lost the race took the test with it.

  Model weights belong to the machine, not to a project, so `cache.models_dir` is now a
  field of its own and defaults to the platform cache directory whatever `cache.dir` says.
  In `dev-ai` that is the named volume, so the checkpoint is fetched once for the whole
  suite. **The `ai` suite went from 206 s to 48 s** and stopped failing. Any user with a
  per project cache directory was paying the same cost silently.

## 1. Provider infrastructure

- [x] 1.1 Add `autocut/core/providers/__init__.py` with `find_key()`, `set_key()`, `clear_key()` over environment and keyring, the `VisionProvider` protocol and `cloud_enabled(config, no_cloud) -> tuple[bool, str]`. Verify with unit tests: environment wins over keyring, no key disables, flag disables, and no key value appears in any log record.

  17 tests. `cloud_enabled` returns the reason with the answer, so the CLI prints one line
  saying which of the three switched cloud off rather than a run that quietly did nothing.
  The order it checks in is the order a user would ask: the flag, then the configuration,
  then the key.

  `has_key()` sits beside `find_key()` for callers that only need to know whether one
  exists, which is every caller except the one that builds the client.

  The key lookup moved here from `doctor.py`, where `m3-embeddings` parked it with the
  service and username this change specifies. `doctor` now imports it.

- [x] 1.2 Add `autocut/core/providers/openrouter.py` with the httpx client, backoff, consecutive failure abort, usage-based cost, and `describe_frame(jpeg_bytes, labels) -> Description | ProviderError`. Verify with unit tests using a mocked transport: retry on 429 and 503, immediate failure on 400, abort after `max_failures`, cost sum, payload contains only image, prompt and model.

  23 tests over a mocked transport, so nothing here touches the network.

  Two departures. **The consecutive failure abort lives in `describe.py`, not here**, which
  is where the design puts it: it is a property of the step over many segments, and the
  provider only ever sees one. It is tested there. And **`response_format` is not sent**.
  The design says to send it "when the model supports it", which is not knowable without
  a key, and a model that rejects it would fail every request in the run. The prompt asks
  for a bare JSON object, fences are stripped, and a malformed answer costs the one
  correction retry the spec already allows.

  The cost comes from `usage.cost` as the provider reports it, requested with
  `usage: {"include": true}`, rather than from a price table in this repository that would
  go stale. A response with no usage block costs 0.0 rather than failing.

  `describe_frame` returns a `Description` even for an answer that did not parse, with
  `raw` set and the three fields empty: it was paid for, so its cost is counted, and
  whether it is worth a correction is the describe step's decision.

- [x] 1.3 Add `autocut key set` and `autocut key clear` commands and extend `autocut doctor` with key presence and the configured vision model. Verify with `CliRunner` tests using a mocked keyring.

  `autocut key set` reads the value without echoing when `--value` is not given, refuses
  an empty one, and reports a missing keyring backend rather than raising. Neither command
  prints the key. The doctor line now names the model and says when `providers.cloud` is
  false despite a key being present, which is a common way to be confused.

## 2. Descriptions

- [x] 2.1 Add `autocut/core/describe.py` with response validation (fences stripped, one correction retry), cache read and write under the file's cache entry, tag merge with `source: cloud`, caption and aesthetic storage, and `describe_project(manifest, config, progress, scope)`. Verify with unit tests for valid, invalid-twice, cached and scope-selected scenarios using a fake provider.

  29 tests. Answers are cached at
  `<cache>/descriptions/<model>/v<prompt_version>/<embedding ref>.json`, so changing either
  the model or the prompt version invalidates them and a re-analysis that moves the shot
  boundaries invalidates them too. The raw answer is not stored: it is the largest field
  and is never needed again.

  Validation corrects rather than rejects where it can. A caption of thirty words is
  trimmed to twenty, an aesthetic of 11 is clamped to 10, tags are lowercased and cut to
  five. Spending a second request to ask again for something the model already answered
  would be waste. An answer with none of the three fields is the case that earns the
  correction retry, and a second bad answer is recorded as a failure on the segment.

  One addition the task does not name: **`describe_project` scores the project again** when
  `weights.aesthetic` is above zero. Scoring happens during analysis, before any
  description exists, and selection reads scores without computing them, so without this
  the aesthetic weight would have no effect until the next analysis.

- [x] 2.2 Add `Tag` merge rules in `autocut/core/tags.py` (local re-run keeps cloud tags, cloud dominates) and `AnalysisRun` fields `cloud_model`, `cloud_requests`, `cloud_cost_usd`. Verify with unit tests for the three scenarios in the modified `semantic-tags` spec and the manifest round trip.

  The merge rules were already half in place: `tag_project` replaces only `local` tags, so
  cloud tags survive a local re-run. What this change adds is the dominant tag preferring
  the first cloud tag, which needed the cloud tags to be `primary` and to keep the order
  the model returned them in. `apply_description` replaces only cloud tags, so describing
  twice does not pile them up.

- [x] 2.3 Add `Metrics.aesthetic` to `SCORED_METRICS` when `weights.aesthetic` is above zero. Verify with a score unit test that the weight changes scores only when descriptions exist.

  The metric is in the table unconditionally and `_composite` skips it for a class where
  any segment lacks a value. Partial coverage is the real case, since
  `describe_scope: selected` describes only the final clips, and ranking a described
  segment against an undescribed one on a number only the first one has would be worse
  than leaving the metric out.

  The test needed one adjustment worth recording: at an aesthetic weight of 1.0 the metric
  exactly cancels the sharpness weight on a two segment pair and both score 0.5, so the
  test uses 3.0 to make the flip unambiguous.

- [x] 2.4 Add `autocut describe <project> [--scope candidates|selected]`, `--no-cloud` on every command, and the call from `autocut analyze` after `tag`. Verify with `CliRunner` tests for enabled, no key and flag paths, asserting no network call in the last two.

  23 tests. The two offline paths replace `httpx.Client` with something that raises, so a
  run that is supposed to make no request fails the test rather than quietly making one.

  `--no-cloud` is applied inside `_load_config`, so it means the same thing on every
  command: this run reaches no provider. On a command that makes no provider call it still
  has an effect worth having, since `doctor` then reports the run as it actually is.

## 3. Report

- [x] 3.1 Show caption, cloud tags distinguished from local, aesthetic value and the header cost line. Verify with report unit tests for the described card and cloud cost scenarios.

  Nine tests. The caption sits under the chip row, the aesthetic is a chip showing the 1 to
  10 the model was asked for rather than the 0 to 1 it is stored as, a cloud tag is styled
  apart from a local one, and a segment whose description failed says why instead of
  looking simply undescribed. The header panel appears only when a model actually ran.

## 4. Validation

- [ ] 4.1 With the real key in the environment, run `autocut describe` on the Sardinia project with `describe_scope: candidates`. Record in this task: request count, cost, wall time, three captions that are right, any caption that is wrong, and how the dominant tags changed the export names. Run it a second time and confirm zero requests. Re-run `select` with `weights.aesthetic = 1.0` and record how many selections changed.

  **Pending: no key.** `OPENROUTER_API_KEY` was not in the implementer's environment for
  this run, and reading it from the repository's `.env` is blocked by policy. Nothing here
  has been measured against a live provider.

  What was verified on the real footage instead is the path that runs without one. On the
  72 file Sardinia set `autocut analyze` completed in 13.0 s, printed
  `Descriptions skipped: no key: neither OPENROUTER_API_KEY nor a keychain entry` as its
  one line, recorded `cloud_model: none` on the run, and left every caption empty. Select
  and export then behaved exactly as on the `m3-tagging` branch: 29 clips, 49 clusters, 19
  candidates held back by the tag share cap, 76.5 s of edit, exported in 135.2 s. The
  export is at `~/Documents/autocut/edit-sardegna-m3-cloud`.

  To finish this task: export the key into the shell and run
  `autocut describe ~/Documents/autocut/edit-sardegna-m3-cloud`, then run it a second time
  and confirm `0 requests, 60 from cache`. The numbers the task asks for come from the two
  lines the command prints. With `describe_scope: candidates` the run is 60 requests; at
  the Gemini Flash rate for one 320 px image and a short answer that is a few cents.

- [x] 4.2 Update `SPEC.md` sections 5.1 and 8 (modules 3, 4, 5) and `autocut.example.toml`. Run `make lint` and `make docker-test`, commit on branch `feat/m3-cloud-providers` following `sf-commit-convention`, open a pull request.

  Section 5.1 gains the payload boundary field by field, the key handling, and the two
  bounds on failure. Section 8 module 4 describes the caption as built and module 5 the
  aesthetic, including why the weight changes nothing until descriptions exist. Section 10
  lists `autocut describe` and `autocut key set`.

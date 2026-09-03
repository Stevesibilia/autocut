## 1. Provider infrastructure

- [ ] 1.1 Add `autocut/core/providers/__init__.py` with `find_key()`, `set_key()`, `clear_key()` over environment and keyring, the `VisionProvider` protocol and `cloud_enabled(config, no_cloud) -> tuple[bool, str]`. Verify with unit tests: environment wins over keyring, no key disables, flag disables, and no key value appears in any log record.
- [ ] 1.2 Add `autocut/core/providers/openrouter.py` with the httpx client, backoff, consecutive failure abort, usage-based cost, and `describe_frame(jpeg_bytes, labels) -> Description | ProviderError`. Verify with unit tests using a mocked transport: retry on 429 and 503, immediate failure on 400, abort after `max_failures`, cost sum, payload contains only image, prompt and model.
- [ ] 1.3 Add `autocut key set` and `autocut key clear` commands and extend `autocut doctor` with key presence and the configured vision model. Verify with `CliRunner` tests using a mocked keyring.

## 2. Descriptions

- [ ] 2.1 Add `autocut/core/describe.py` with response validation (fences stripped, one correction retry), cache read and write under the file's cache entry, tag merge with `source: cloud`, caption and aesthetic storage, and `describe_project(manifest, config, progress, scope)`. Verify with unit tests for valid, invalid-twice, cached and scope-selected scenarios using a fake provider.
- [ ] 2.2 Add `Tag` merge rules in `autocut/core/tags.py` (local re-run keeps cloud tags, cloud dominates) and `AnalysisRun` fields `cloud_model`, `cloud_requests`, `cloud_cost_usd`. Verify with unit tests for the three scenarios in the modified `semantic-tags` spec and the manifest round trip.
- [ ] 2.3 Add `Metrics.aesthetic` to `SCORED_METRICS` when `weights.aesthetic` is above zero. Verify with a score unit test that the weight changes scores only when descriptions exist.
- [ ] 2.4 Add `autocut describe <project> [--scope candidates|selected]`, `--no-cloud` on every command, and the call from `autocut analyze` after `tag`. Verify with `CliRunner` tests for enabled, no key and flag paths, asserting no network call in the last two.

## 3. Report

- [ ] 3.1 Show caption, cloud tags distinguished from local, aesthetic value and the header cost line. Verify with report unit tests for the described card and cloud cost scenarios.

## 4. Validation

- [ ] 4.1 With the real key in the environment, run `autocut describe` on the Sardinia project with `describe_scope: candidates`. Record in this task: request count, cost, wall time, three captions that are right, any caption that is wrong, and how the dominant tags changed the export names. Run it a second time and confirm zero requests. Re-run `select` with `weights.aesthetic = 1.0` and record how many selections changed.
- [ ] 4.2 Update `SPEC.md` sections 5.1 and 8 (modules 3, 4, 5) and `autocut.example.toml`. Run `make lint` and `make docker-test`, commit on branch `feat/m3-cloud-providers` following `sf-commit-convention`, open a pull request.

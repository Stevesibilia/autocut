## 1. Window fix (design decision 8), one commit

- [x] 1.1 `METRIC_ARRAYS.get` in `window.frame_scores`, with its comment.
- [x] 1.2 Tests: `test_window.py` (an aesthetic weight gives the same frame scores as weight 0) and `test_select.py` (`select_clips` with `weights.aesthetic = 1.0` completes, and gives the same windows).
- [x] 1.3 Commit: `fix(core): keep segment-only metrics out of the window search`.

## 2. Head, tower, cache and stage (decisions 1 to 6, 9), one commit

- [x] 2.1 Download the head and check its size and SHA-256. Add it and its licence under `autocut/core/models/`, the `artifacts` entry and the `THIRD_PARTY_LICENSES.md` row.
- [x] 2.2 In the `ai` container, check that `("ViT-B-32-quickgelu", "openai")` is in `open_clip.list_pretrained()` and loads without a QuickGELU warning. Quote the result in the hand-back.
- [x] 2.3 `aesthetic.py` (constants, `load_head`, `rate`, `score_aesthetics`, `AestheticResult`, `AESTHETIC_RANGE` moved in), `load_model` and `weights_present` taking `name`, `CacheEntry.aesthetic` and `aesthetic_model` through `write_entry` and `read_entry`, `Metrics.aesthetic_source`, `apply_description` setting `cloud`, `describe._rescore` through `score.rescore`, and the `providers.aesthetic` description, example toml and snapshot.
- [x] 2.4 Unit tests (no torch; fake the tower with the `test_embeddings.py` fakes, `encoder_returning` and `available_extra`):
  - `rate` against a hand-computed value for a known weight and bias;
  - the bundled head's SHA-256;
  - every spec scenario in `specs/frame-embeddings/spec.md`;
  - clipping to 1 to 10;
  - the rescore happens only when `weights.aesthetic > 0` and a value changed;
  - `load_model(name=...)` and `weights_present(name=...)` keep today's behaviour for `name=None`;
  - the cache round-trip of `aesthetic` and `aesthetic_model`;
  - a manifest with `aesthetic_source` loads, and one without it loads with `None`.
- [x] 2.5 An `ai`-marked integration test in `tests/integration/test_aesthetic_ai.py`: the real tower and head on the synthetic fixtures' thumbnails. Every rating is finite and within 1 to 10, and the test prints min, median and max. Run it with `make docker-test-ai`.
- [ ] 2.6 Commit: `feat(core): score aesthetics locally with the laion predictor`.

## 3. Pipeline, CLI, GUI, doctor (decision 7), one commit

- [x] 3.1 `run_aesthetic`, `AnalysisOutcome.aesthetic`, the call in `analyze_project` and in `autocut embed`, `output.print_aesthetic`, the GUI `describe_outcome` line, and the `aesthetic_weights` doctor check.
- [x] 3.2 Tests:
  - `test_pipeline` or `test_analyze`: the stage runs after embed and before describe;
  - `test_cli_embed.py`: the printed line when enabled, nothing new when disabled;
  - `test_doctor.py`: the check appears only when enabled;
  - the GUI summary line in the analysis screen tests.
- [x] 3.3 Commit: `feat(cli): report local aesthetic scoring`.

## 4. Docs (decision 10), one commit

- [ ] 4.1 ADR 15, the `SPEC.md` sections, `CHANGELOG.md`. Run `sjust format-md` on each Markdown file.
- [ ] 4.2 Commit: `docs: record the local aesthetic predictor`.

## 5. Gates and hand-back

- [ ] 5.1 `make lint` and `openspec validate local-aesthetic-predictor --strict`.
- [ ] 5.2 Through the test runner, run `make test`, `make docker-test-ai` and `make docker-test-gui`, and quote the counts.
- [ ] 5.3 The rating spread from 2.5, and the QuickGELU check from 2.2.
- [ ] 5.4 Tick these boxes, push the branch and hand back.

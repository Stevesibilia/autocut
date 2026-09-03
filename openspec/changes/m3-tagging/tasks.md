## 1. Schema and config

- [ ] 1.1 Add `Tag` to `autocut/core/manifest.py`, change `Segment.tags` to `list[Tag]` with a validator that upgrades a list of strings, and add a `dominant_tag` property. Verify with manifest round trip tests for both shapes.
- [ ] 1.2 Add `tags.labels` (label, optional prompt), `tags.threshold`, `tags.max_per_segment` and `selection.max_share_per_tag` to `autocut/core/config.py` and `autocut.example.toml` with the shipped defaults. Verify with config default tests.

## 2. Tagger

- [ ] 2.1 Add `autocut/core/tags.py` with `encode_labels(labels, model)`, `tag_embeddings(embeddings, label_matrix, threshold, max_per_segment) -> list[list[Tag]]` and `tag_project(manifest, config, progress)`. Verify with unit tests on synthetic embeddings and a mocked text encoder for the beach, ambiguous and no-embedding scenarios.
- [ ] 2.2 Add `autocut tag <project>` and call it from `autocut analyze` after `embed`. Verify with `CliRunner` tests for the tagged, skipped and custom-label paths.
- [ ] 2.3 Add an `ai` marked test tagging the synthetic fixtures with the real model and asserting `smptebars` receives no tag above threshold. Verify in `dev-ai`.

## 3. Consumers

- [ ] 3.1 Add the tag share cap to `autocut/core/select.py`. Verify with unit tests for the two new scenarios in the modified `clip-selection` spec.
- [ ] 3.2 Use the dominant tag in `autocut/core/naming.py`. Verify with the tagged name scenario test.
- [ ] 3.3 Show tags on cards, add the tag filter and header counts to the report. Verify with report unit tests for the tagged card and tag filter scenarios.

## 4. Validation

- [ ] 4.1 Run `autocut tag` on the real Sardinia project. Record in this task: tag distribution over the 60 candidates, the three most confident tags with their segments, the confusions a person would object to, and wall time. Re-run `select` and `export` and record how many names changed from `clip` and how the tag share cap changed the selection.
- [ ] 4.2 Update `SPEC.md` section 8 module 3. Run `make lint` and `make docker-test`, commit on branch `feat/m3-tagging` following `sf-commit-convention`, open a pull request.

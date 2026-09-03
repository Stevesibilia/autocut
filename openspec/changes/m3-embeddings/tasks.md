## 1. Extra and environment

- [ ] 1.1 Pin the `ai` extra in `pyproject.toml` to torch and open_clip versions that have wheels for Linux x86_64 and macOS arm64 on Python 3.11 through 3.14, verified against PyPI per AGENTS.md. Verify with `pip download --only-binary :all:` for both platforms in the dev container.
- [ ] 1.2 Add a `Dockerfile.dev` target `ai` that installs the extra, a compose service `dev-ai`, and an `ai` pytest marker skipped when torch does not import. Verify `docker compose run --rm dev-ai pytest -q -m ai` runs the marked tests.
- [ ] 1.3 Add `autocut/core/doctor.py` with `inspect_environment(config) -> DoctorReport` and the `autocut doctor [--json]` command. Verify with unit tests mocking each probe and a `CliRunner` test for exit status with and without ffmpeg on PATH.

## 2. Embeddings

- [ ] 2.1 Add `autocut/core/embeddings.py` with `available() -> str | None`, `select_device()`, `load_model(config)`, `embed_frames(frames, model, device, batch_size, progress) -> np.ndarray` and `embed_project(manifest, config, progress)` reading thumbnails from cache entries and writing `embeddings` and `embedding_model` back. Verify with unit tests using a mocked encoder: shapes, normalization, batch count equals progress events, model change triggers recompute, same model skips.
- [ ] 2.2 Extend the cache entry with `embeddings` and `embedding_model` and `AnalysisRun` with `embedding_model` and `embedding_device`. Verify with the cache round trip and manifest tests.
- [ ] 2.3 Wire `autocut embed <project>` and call it at the end of `autocut analyze` when enabled and available, printing one skip line otherwise. Verify with `CliRunner` tests for the enabled, disabled and unavailable paths.
- [ ] 2.4 Add the `ai` marked integration test that embeds the synthetic fixtures with the real model and asserts the blurred and sharp fixtures of the same source have cosine similarity above 0.9 while `smptebars` and `testsrc2` are below 0.7. Verify it passes in `dev-ai`.

## 3. Semantic signal

- [ ] 3.1 Add `SemanticSignal` to `autocut/core/similarity.py` with `similarity.semantic_floor` and weight in config, and the hash exclusion rule in the combiner. Verify with unit tests for the four scenarios in the modified `similarity-signals` spec.

## 4. Validation

- [ ] 4.1 Run `autocut embed` on the real Sardinia project on the Linux CPU and record wall time and device. Run `autocut select` with and without the semantic signal and record: cluster count, number of `lost_to` candidates, and how many of the 40 selections changed. Open the report and note whether the new clusters group shots a person would call the same scene.
- [ ] 4.2 Update `SPEC.md` section 8 module 1 and section 6.1 with the pinned model and the doctor command. Run `make lint` and `make docker-test`, commit on branch `feat/m3-embeddings` following `sf-commit-convention`, open a pull request.

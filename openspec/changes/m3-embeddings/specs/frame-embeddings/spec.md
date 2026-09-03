## Purpose

Frame embeddings give every segment a semantic vector from a local vision model, so similarity, tagging and the soundtrack prompt can reason about what a shot shows rather than how its pixels are arranged.

## ADDED Requirements

### Requirement: Optional and gracefully degrading

Embedding SHALL run only when `providers.local_embeddings` is true and the `ai` extra is importable. When the extra is missing, the system MUST continue without embeddings, record `embedding_model: none` on the run, and emit one warning, never an error.

#### Scenario: Extra not installed

- **WHEN** `autocut analyze` runs in an environment without torch
- **THEN** analysis completes, no segment has an embedding, the run records `embedding_model: none` and the CLI prints one line saying embeddings were skipped

#### Scenario: Disabled by configuration

- **WHEN** `providers.local_embeddings` is false
- **THEN** no model is loaded and no embedding step runs

### Requirement: One embedding per segment from the cached thumbnail

The system SHALL compute one normalized embedding per segment from its cached thumbnail frame using the configured model (`providers.embedding_model`, default a CLIP ViT-B-32 checkpoint), in batches, on the best available device in the order CUDA, MPS, CPU. Embeddings MUST NOT require decoding video again.

#### Scenario: Cached frames only

- **WHEN** embeddings are computed for an analyzed project
- **THEN** no ffmpeg process is started

#### Scenario: Device selection

- **WHEN** the machine has an Apple Silicon GPU
- **THEN** the run records `embedding_device: mps`

### Requirement: Stored in the cache, referenced from the manifest

Embeddings SHALL be stored in the file's analysis cache entry together with the model identifier, and each segment SHALL carry an `embedding_ref` naming the entry and index. A cache entry whose stored model identifier differs from the configured one MUST be treated as having no embeddings, without invalidating its metric arrays.

#### Scenario: Model changed

- **WHEN** `providers.embedding_model` changes
- **THEN** embeddings are recomputed from cached frames and metrics are not recomputed

#### Scenario: Re-run is free

- **WHEN** `autocut analyze` runs again with the same model
- **THEN** no embedding is recomputed

### Requirement: Weights downloaded once

Model weights SHALL be downloaded on first use into the platform cache directory under `autocut/models/`, and every later run MUST work offline. `autocut doctor` SHALL report whether the weights are present.

#### Scenario: Second run offline

- **WHEN** weights are present and the network is unavailable
- **THEN** embedding runs without error

### Requirement: Embed command

`autocut embed <project>` SHALL compute missing embeddings for an analyzed project without re-running analysis, and SHALL be what `autocut analyze` calls at its end when embeddings are enabled.

#### Scenario: Embed after the fact

- **WHEN** a project was analyzed without the extra and the extra is installed later
- **THEN** `autocut embed` fills embeddings for every segment from the cache

### Requirement: Progress events

The embedding step SHALL emit an `embed` progress event per batch through the core callback and MUST NOT print from the core.

#### Scenario: Progress bar

- **WHEN** 60 segments are embedded in batches of 16
- **THEN** four progress events are emitted

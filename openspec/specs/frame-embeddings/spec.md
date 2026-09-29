# frame-embeddings Specification

## Purpose

Frame embeddings give every segment a semantic vector from a local vision model, so similarity, tagging and the soundtrack prompt can reason about what a shot shows rather than how its pixels are arranged.

## Requirements

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

### Requirement: Local aesthetic score

When `providers.aesthetic` is on and the `ai` extra is installed, every segment SHALL receive `Metrics.aesthetic` from the bundled LAION aesthetic head applied to its cached thumbnail, embedded with the OpenAI ViT-B/32 CLIP tower, as a 1 to 10 rating scaled to 0 to 1, with `aesthetic_source` set to `local`. The per-shot ratings SHALL be cached with the model id and reused while it matches. A cloud value SHALL never be overwritten by a local one. When `weights.aesthetic` is above 0 and any value changed, segment scores SHALL be recomputed. When the feature is off, local values SHALL be removed and no tower SHALL load.

#### Scenario: Local only

- **WHEN** a project is analysed with `providers.aesthetic` on and no cloud key
- **THEN** every segment with a cached thumbnail has an aesthetic between 0.1 and 1.0 marked `local`

#### Scenario: Cloud wins

- **WHEN** a segment has a cloud aesthetic and the local stage runs again
- **THEN** its aesthetic and source are unchanged, and the stage counts it as kept from cloud

#### Scenario: Legacy manifest

- **WHEN** a manifest from before this change has an aesthetic with no source
- **THEN** the value is treated as a cloud value

#### Scenario: Cached ratings

- **WHEN** the stage runs twice on an unchanged project
- **THEN** the second run loads no model and reports every file from cache

#### Scenario: Turned off

- **WHEN** the stage runs with `providers.aesthetic` off on a project with local values
- **THEN** the local values are removed, cloud values stay, and no model loads

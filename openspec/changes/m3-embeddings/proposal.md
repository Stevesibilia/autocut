## Why

The classic similarity signals catch near identical frames but not the same bay filmed from two angles, and the M2 validation showed the visual hash separating groups by only 0.08. A semantic embedding per segment is the enabler for better deduplication, for tagging and for the soundtrack prompt, and SPEC.md section 8 lists it as the first AI module to build. This change adds it as an optional, local, gracefully degrading layer.

## What Changes

- Optional `autocut[ai]` extra with torch and open_clip; the core imports them lazily and works without them.
- One image embedding per segment computed from the cached thumbnail frame with a local CLIP model, on MPS, CUDA or CPU, weights downloaded once into the platform cache directory.
- Embeddings stored in the analysis cache entry and referenced from the manifest, keyed so a model change invalidates them without re-decoding video.
- A `semantic` similarity signal (cosine similarity mapped to 0 to 1) added to the existing signal list with its own weight, enabled when embeddings exist.
- `autocut analyze` runs the embedding step after metrics when enabled and available, with progress events; `autocut embed <project>` runs it on an existing project without re-analysis.
- `autocut doctor` reports what the environment provides: ffmpeg version, hardware decoder decision, whether the `ai` extra is importable, which compute device would be used, which model weights are present, whether a cloud key is present.

## Capabilities

### New Capabilities

- `frame-embeddings`: computing, caching and exposing a semantic embedding per segment with graceful degradation.
- `environment-doctor`: reporting the runtime capabilities available to AutoCut on this machine.

### Modified Capabilities

- `similarity-signals`: a semantic signal joins the combination and the visual fallback is used only when it is absent.

## Impact

- New modules under `autocut/core/`: `embeddings.py`, `doctor.py`; `similarity.py` gains one signal.
- `pyproject.toml`: `ai` extra pinned to versions with wheels for Linux x86_64 and macOS arm64 on Python 3.11 to 3.14; Dockerfile.dev gets a second target with the extra for CI of the embedding tests, gated by a marker so the default CI stays light.
- `autocut/core/manifest.py`: `Segment.embedding_ref` is filled; `AnalysisRun` gains `embedding_model` and `embedding_device`.
- Cache entry format gains an `embeddings` array and a `embedding_model` field; `analysis_schema_version` unchanged because metric arrays do not change.
- Real footage: 60 candidates embedded on the Linux CPU, timing recorded; cluster and selection differences with and without the semantic signal recorded.

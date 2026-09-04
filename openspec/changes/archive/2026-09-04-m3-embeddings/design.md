## Context

The cache already holds one 320 px thumbnail frame per segment, so embedding costs one forward pass per segment and no decoding. ADR 4 fixed that embeddings stay local. The `ai` extra exists in `pyproject.toml` but nothing imports it. The development host has no CUDA and a CPU-only torch; the production MacBook has MPS.

## Goals / Non-Goals

**Goals:**

- Zero cost for users without the extra: no import, no warning noise beyond one line.
- Embeddings ride along in the existing cache entry so a project on known footage embeds from disk.
- One place to add a second image model later.

**Non-Goals:**

- Text embeddings and zero-shot labels (change `m3-tagging`).
- Cloud embeddings (ADR 4 rules them out).
- Aesthetic predictor and faces (M4b).

## Decisions

**Model.** open_clip `ViT-B-32` with `laion2b_s34b_b79k` weights, 512 dimensions, about 350 MB. Alternatives: SigLIP base gives better zero-shot but needs transformers and is twice the size; ViT-L is four times slower on CPU for a marginal gain at 60 to 500 segments. Configurable through `providers.embedding_model` as `architecture/pretrained`.

**Lazy import.** `embeddings.py` imports torch and open_clip inside a function guarded by a try; `available()` returns a reason string. The CLI and `doctor` use the same function.

**Device order.** CUDA, MPS, CPU. On MPS float16 is used; CPU stays float32. Batch size 16 by default, configurable, because the frames are already in memory as one array.

**Storage.** Cache entry gains `embeddings` (float32 `N x 512`, one per segment thumbnail, in shot order) and `embedding_model`. Manifest `embedding_ref` is `<file_key>:<segment_index>`. Loading for selection reads only the `embeddings` array of each file's `.npz`, which is small.

**Weights location.** `platformdirs.user_cache_dir("autocut") / "models"` passed to open_clip as `cache_dir`, so offline runs work and the bundle (ADR 7) can pre-seed it.

**Signal integration.** `SemanticSignal` implements the existing `SimilaritySignal` protocol; `available(a, b)` is true when both embeddings exist. The combiner drops the hash signal for a pair when the semantic one is available, per the modified requirement. Default weight 0.5, replacing the visual weight rather than adding to it.

**Doctor.** Pure function returning a dataclass; the CLI renders text or JSON. Reuses `hwaccel.decide` and `embeddings.available`.

**Tests.** Unit tests run without torch by mocking the encoder with a deterministic function on the frame array. One integration test marked `ai` runs the real model on the synthetic fixtures when the extra is importable, and CI runs it in a second Docker target built with the extra, on Linux only.

## Risks / Trade-offs

- [torch wheel size in CI] → second Docker target cached by layer; default job unchanged.
- [MPS float16 numerical drift versus CPU] → embeddings are normalized and used for cosine only; a tolerance test compares CPU and mocked outputs, real MPS is checked on the Mac and recorded.
- [Model download on first run needs network] → `doctor` says so; `autocut embed` prints the download once.
- [Semantic signal makes two sunsets in different bays similar] → spatial and temporal signals stay in the mean; validation compares cluster counts with and without.

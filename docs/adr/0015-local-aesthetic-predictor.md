# 15. Local aesthetic predictor on a second CLIP tower

Date: 2026-09-28

## Status

Accepted

## Context

`Metrics.aesthetic` was filled only by the cloud `describe` step, which needs a paid key. SPEC §8 item 5 kept a local predictor on CLIP embeddings as the M4b option, and ADR 4 listed aesthetic judgment among the things a hosted model serves. Setting `weights.aesthetic` above 0 also crashed selection, because the window search had no per-frame array for it.

LAION publishes a small linear head for the ViT-B/32 aesthetic predictor: 3 KB, MIT licensed. It was trained on the image vectors of OpenAI's CLIP ViT-B/32. AutoCut embeds with `ViT-B-32/laion2b_s34b_b79k` for deduplication and tags, which is a different vector space, so the head cannot be applied to those vectors.

## Decision

We will score every segment locally with LAION's head when `providers.aesthetic` is on and the `ai` extra is installed. The head runs on embeddings of the cached per-shot thumbnails from a second tower, `ViT-B-32-quickgelu` with the OpenAI weights, used only for this. The deduplication and tag embeddings stay on laion2b.

The tower is a constant, not configuration, because the head is only valid for it. The head is bundled as published in `autocut/core/models/`, with its licence beside it, so its provenance can be checked by hash. The ratings are cached per file with a model id, and reused while it matches.

A cloud judgment always wins. `Metrics.aesthetic_source` records whether a value is `local` or `cloud`, and a value with no source, written before this change, counts as cloud. Turning the feature off removes the local values and keeps the cloud ones.

The best-window search ignores scored metrics that have no per-frame array. The aesthetic moves a segment's score, not the choice of window inside it.

This amends SPEC §8 item 5, and ADR 4's list of what the cloud serves: aesthetic judgment has a local implementation now, and the cloud one overrides it.

## Consequences

A second 350 MB checkpoint is downloaded on first use when the feature is on, and a run pays one more forward pass per shot, once per file. Nothing changes for a user who leaves the feature off, and no dependency is added.

The rating spread on real footage is unproven by the fixtures, which are test cards; it is checked on real thumbnails before release. On MPS the vectors are cast to float32 before the head, because a linear head is more sensitive to half precision drift than the cosine comparisons the embedding path serves.

A different head or tower needs a new model id, a new bundled file and a new ADR.

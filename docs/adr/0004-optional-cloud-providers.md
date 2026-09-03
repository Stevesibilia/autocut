# 4. Optional cloud providers behind local baselines

Date: 2026-09-03

## Status

Accepted

## Context

The original draft required that everything run locally, with no external API calls. During review the owner relaxed that constraint: cloud models are welcome where they give better results, and an OpenRouter key is available.

Some steps gain a lot from a hosted model. Semantic tagging and captioning with a vision language model are far more specific than zero-shot CLIP labels, and a caption per clip turns the soundtrack prompt from a tag list into a description of the actual video. Prompt refinement with an LLM was already planned as a local option and is simpler as a hosted call. Other steps gain little: frame embeddings for similarity are cheap to compute locally and no hosted embedding endpoint is available through OpenRouter.

Cloud calls introduce cost, latency, network dependency and a privacy boundary. The material is family footage, so what leaves the machine must be deliberate and small. The app must also keep working offline and without a key, since the GUI is meant to be a standalone product.

## Decision

We will put every step that can be served by a hosted model behind a provider interface with a local implementation that always exists. Cloud providers are used for semantic tags, captions, aesthetic judgment and prompt refinement through OpenRouter, one downscaled 320 px JPEG per segment for vision calls and only derived signals for text calls. Frame embeddings for deduplication stay local. Reverse geocoding runs online with an on-disk cache.

Cloud features enable themselves when `OPENROUTER_API_KEY` is present in the environment or the OS keychain, and disable with `--no-cloud` or `providers.cloud = false`. The model id is configurable. Full video files never leave the machine.

## Consequences

Tags and captions become good enough to drive category balancing and a specific soundtrack prompt without training or hosting anything. The local path stays complete, so tests and CI run without a key and the packaged app works offline.

Every provider needs two implementations and the behavior differs between them, which must be visible in the report so the user knows which path produced a result. A project analyzed with cloud tags and reopened without a key shows cached tags but cannot refresh them. Costs are small (hundreds of calls per project with a Flash class model) but nonzero, and the app must never retry in a loop. The privacy boundary is documented in the spec and enforced in code by passing only the thumbnail path and derived fields to provider calls.

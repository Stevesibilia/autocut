## Context

ADR 4 allows hosted models behind a provider interface with a local baseline, sends only downscaled frames and derived signals, and gates everything on a key and an opt-out. `m3-tagging` gives the tag schema with provenance. OpenRouter exposes many vision models behind one OpenAI-compatible endpoint, and the user has a key. No embedding endpoint is used (ADR 4).

## Goals / Non-Goals

**Goals:**

- One request per segment, cached forever per model and prompt version, so a project costs cents once.
- A provider interface small enough that a second host or a local vision LLM is a new module, not a refactor.
- Failures never break a run and never loop.

**Non-Goals:**

- Prompt refinement for the soundtrack (M4).
- Sending anything beyond the thumbnail.
- Cloud music generation.

## Decisions

**Client.** `httpx.Client` with a 60 s timeout against the OpenRouter chat completions endpoint, `response_format` JSON when the model supports it, image as a base64 data URL. Concurrency through a thread pool of `max_concurrency` (default 4), because the work is network bound and the frames are already in memory. Alternative `asyncio`, rejected to keep the core synchronous like everything else.

**Retry policy.** 429 and 5xx retried with backoff 1, 2, 4, 8 s up to `max_retries` (default 4); 4xx other than 429 fail immediately. `max_failures` (default 8) consecutive failures abort the describe step for the run. This is the rule against infinite retries that ADR 4 requires.

**Prompt.** One fixed system prompt versioned by `prompt_version` in config, asking for the JSON object with the label set inlined. Changing the wording bumps the version and invalidates the cached responses on purpose.

**Model default.** `google/gemini-2.5-flash` for cost; configurable. The model id is recorded on the run and in each cached response.

**Key storage.** `keyring` with service `autocut` and username `openrouter`; the GUI settings screen in M5 uses the same call. Environment variable wins for scripting. `doctor` reports presence, never the value.

**Cache.** Responses stored as JSON next to the file's cache entry under `descriptions/<model>/<prompt_version>/<segment_index>.json`. Keyed on the embedding reference so a re-analysis with new segment boundaries invalidates naturally.

**Aesthetic into score.** `Metrics.aesthetic = value / 10`, weight default 0 (existing config). When above zero it joins `SCORED_METRICS` with per-class rank normalization like the others.

**Scope default.** `candidates` (about 60 on the Sardinia set, a few cents). `selected` is for large projects where only the final clips need captions for the soundtrack.

## Risks / Trade-offs

- [Model returns markdown-fenced JSON] → strip fences before parsing, one correction retry, then failure recorded.
- [Cost surprises] → cost printed after every run and shown in the report header; `describe_scope: selected` documented.
- [Key leaks through logs] → the client never logs headers; a unit test asserts the key does not appear in any log record or in the manifest.
- [Cloud tags flood the dominant tag with free words] → labels from the configured set are requested first; the report distinguishes sources so the user sees the effect.

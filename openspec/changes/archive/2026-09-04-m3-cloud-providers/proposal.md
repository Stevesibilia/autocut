## Why

Local zero-shot tags are coarse and say nothing about what is happening in a shot. A hosted vision model, given one 320 px thumbnail, returns specific tags and a one-sentence caption for a fraction of a cent per segment, and captions are the input that turns the M4 soundtrack prompt from a tag list into a description of the actual video. ADR 4 allows this behind a provider interface with a local fallback; this change builds the interface and its first provider.

## What Changes

- OpenRouter client with the key from `OPENROUTER_API_KEY` or the OS keychain, bounded concurrency, exponential backoff with a hard retry cap, and per-request cost accounting from response usage.
- Vision provider: for each candidate segment, one request with the thumbnail JPEG and a fixed prompt asking for tags from the configured label set plus free tags, a one-sentence caption and an aesthetic judgment 1 to 10, returned as JSON and validated.
- Responses cached in the analysis cache keyed by model and prompt version, so re-runs cost nothing.
- Tag merge rule: cloud tags and local tags coexist on the segment with their source; the dominant tag prefers cloud when present.
- `Segment.caption` and `Metrics.aesthetic` filled; the aesthetic value enters the score only when `weights.aesthetic` is above zero.
- `--no-cloud` on every command and `providers.cloud = false` disable all of it; `autocut doctor` shows key presence and the configured model.
- `autocut describe <project>` runs the provider on an existing project; `autocut analyze` calls it after tagging when enabled and a key is present.
- Report shows the caption, cloud tags and aesthetic value on each card and the total cost of the run in the header.

## Capabilities

### New Capabilities

- `cloud-providers`: authenticated, rate-limited, cached access to hosted models with strict data minimization.
- `segment-descriptions`: cloud vision tags, captions and aesthetic judgments per segment.

### Modified Capabilities

- `semantic-tags`: the merge rule between local and cloud tags.
- `review-report`: caption, cloud tags, aesthetic value and run cost shown.

## Impact

- New modules under `autocut/core/`: `providers/__init__.py` (interface, key lookup), `providers/openrouter.py`, `describe.py`.
- `autocut/core/config.py`: `providers.vision_model`, `providers.max_concurrency`, `providers.max_retries`, `providers.prompt_version`, `providers.describe_scope` (`candidates` or `selected`).
- `autocut/core/manifest.py`: `AnalysisRun` gains `cloud_model`, `cloud_requests`, `cloud_cost_usd`.
- Dependencies: `httpx` and `keyring` already declared.
- Depends on `m3-tagging`. Privacy boundary: one 320 px JPEG and no metadata per request, documented in `SPEC.md` section 5.1 and shown by `doctor`.

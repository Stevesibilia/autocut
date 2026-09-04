# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Project specification in English with the decisions from the 2026-09-03 review.
- Architecture decision records 1 to 8.
- Repository skeleton: core, cli and gui packages, configuration and manifest schemas, CLI command stubs.
- Synthetic fixture generator and test scaffolding.
- Docker development environment and GitHub Actions workflows for CI and macOS release builds.
- Best window search: the sub-window of target duration with the highest mean per-frame score, stored as a centre and a target duration.
- Classic similarity signals, each switchable: perceptual hash and colour histogram on the segment thumbnail, GPS distance, timestamp distance and motion profile correlation.
- Greedy clip selection with a similarity penalty, per-file, per-cluster and total caps, a minimum share per class and a minimum temporal gap.
- Visual clusters over the combined similarity, so near duplicates group in the report.
- `autocut select` with `--max-clips`, `--duration` and `--diversity`, and `autocut run` chaining analyze, select and report.
- ffmpeg command builder for one clip as a pure function, covering precise re-encode and fast stream copy, frame rate and resolution normalization, pixel format conversion, per-class audio removal, automatic slow motion, the three vertical strategies, and the LUT and lens correction hooks. `export.fps = "auto"` takes the frame rate that the most selected clips reach by whole-number division, lowest on a tie.
- Output naming `{index:03d}_{date}_{class}_{tag}_{duration}s.mp4` into `_selects/`, with `_rejects/` on request and retired outputs moved to `_selects/_stale/`.
- `autocut export` with `--no-audio`, `--fps`, `--fast` and `--rejects`, parallel over clips and resumable: a clip whose output matches its recorded settings is skipped.
- Synthetic fixtures for a clip with an audio track and a 50 fps clip.

- Per-clip durations: each selected clip gets its own length from its class, its score, a hero bonus for the best few and a pass that breaks up runs of the same length, within configured bounds and an optional total. `autocut select --duration <seconds>` sets one length for every clip.
- Motion snap: the window start may move onto a nearby minimum of the motion series, so the cut lands where movement stops rather than partway through a pan.

- Places and visits from GPS and time, and a cap of three clips per visit, so one spot on one outing cannot fill the edit however different the pixels look. Candidates without GPS belong to no place and are never held back by it.
- Candidate share ceiling: `max_clips` is bounded to half the eligible candidates unless `--max-clips` is passed, so a small folder produces a short edit.

- One CLIP embedding per segment, local and optional, computed from the thumbnail frame already in the analysis cache so no video is decoded again. Stored in the cache entry with the model identifier, on CUDA, MPS or CPU in that order. `autocut embed` fills a project analyzed without the `ai` extra, and `autocut analyze` runs it at the end when the extra is installed. Without the extra analysis completes and prints one line.
- Semantic similarity signal, the cosine between two segment embeddings stretched from `similarity.semantic_floor` onto 0 to 1. It replaces the perceptual hash for any pair where both candidates carry an embedding, and a pair missing one falls back to the hash.
- `autocut doctor`, with `--json` and `--sample`: ffmpeg and ffprobe versions, the decoder `auto` would choose and whether it verified, whether the `ai` extra imports, the compute device, whether the model weights are present, whether an OpenRouter key is available, and the cache directory with its size. Exits non-zero only when ffmpeg or ffprobe is missing.
- Zero-shot semantic tags per segment, local, from the cached embeddings and a configurable label set. Labels live in groups scored by one softmax each, so a drone shot over a beach can be both `beach` and `aerial` rather than having to choose; every group carries a null prompt that competes and has to be beaten before a label is emitted, which is what lets a shot end up with no tag at all. `autocut tag` recomputes them in seconds without touching embeddings or metrics, and `autocut analyze` runs it after embedding.
- Tags carry their confidence, their group and their source, and the dominant tag is the most confident one from the primary group. Exported clips are named after it, or `clip` when no subject label won.
- `selection.max_share_per_tag`, a ceiling of 0.5 by default on the share of the edit carrying one dominant tag, lifted like the place cap when nothing else is eligible.
- The review report shows every tag with its confidence and group, marks the one that names the clip, offers a filter by tag and counts the segments carrying each.
- Cloud descriptions per segment through OpenRouter: tags from the configured label set plus free words, a one sentence caption and an aesthetic judgment from 1 to 10, in one request per segment. `autocut describe` runs them and `autocut analyze` calls it after tagging. Answers are cached under the analysis cache per model and prompt version, so a second run over the same project makes no request.
- Cloud stays off unless `providers.cloud` is true, a key is available and `--no-cloud` was not passed. Any of the three disables every call in the run and the CLI names which one did it. `--no-cloud` is accepted by every command.
- `autocut key set` and `autocut key clear` store and remove the OpenRouter key in the OS keychain. The key is prompted for without echo, or piped in with `--stdin`; it is never accepted as a command line argument, where it would be readable in `ps` and kept in the shell history. The key is read from `OPENROUTER_API_KEY` first, and never written to `autocut.toml`, the manifest, the cache or a log line.
- Requests retry on 429 and 5xx with backoff 1, 2, 4, 8 s up to `providers.max_retries`, fail at once on any other 4xx, and stop the describe step after `providers.max_failures` consecutive failures. A failure is recorded on the segment and the run completes.
- Each vision request carries the 320 px thumbnail, the fixed prompt and the model id, and nothing else. A unit test asserts the request body against that.
- `Metrics.aesthetic` joins the composite score when `weights.aesthetic` is above zero, rank normalized per class like every other metric. A class where no segment carries one leaves the metric out, so the weight changes nothing until descriptions exist.
- The review report shows the caption on the card, marks cloud tags apart from local ones, shows the aesthetic value, says why a description failed, and reports the model, the request count and the cost in USD in the header.
- `ai` extra pinned to torch 2.13, torchvision 0.28 and open_clip_torch 3.3, a second `Dockerfile.dev` target and `dev-ai` compose service that install torch from the PyTorch CPU index, `make docker-test-ai`, an `ai` pytest marker that skips when torch does not import, and a CI job that runs the marked tests so the matrix job stays light.

### Changed

- The review report lists selected segments first, with their edit order, best window bounds, visual cluster and the near duplicate a candidate lost to.
- Selection holds back display-vertical candidates when `export.vertical_strategy` is `exclude`, marking them with the reason `vertical` while they stay candidates, so the report shows them as excluded by policy rather than rejected on quality.
- The review report links each selected card to its exported file and marks fast cuts and clips resampled from another frame rate.
- Selected cards show the clip's target duration, the rule that settled it and whether its window was snapped to a motion boundary.
- `export.remove_audio` defaults to true for every class: a default export is silent and the soundtrack carries the sound. Set a class to false in `autocut.toml` to keep its ambience.
- The review report shows each segment's place, offers a filter by place, lists the places with their visits and clip counts, and names the clips that filled a visit on a card the place cap held back.
- The dominant tag prefers the first cloud tag when a segment has one, since a model that looked at the picture is more specific than a zero-shot label set. A local re-run replaces only local tags and leaves cloud tags alone.
- `Segment.tags` is a list of `Tag` records rather than of strings. A manifest written before the change opens unchanged: a string list upgrades to local tags with confidence 1.0.
- Tests that are not marked `ai` no longer touch the real vision model. With the extra installed, every CLI test running `analyze` was downloading the model into its own temporary cache.
- A cache entry whose stored embedding model differs from the configured one reads back with no embeddings and with its metric arrays intact, so changing the model costs one forward pass per shot rather than a re-analysis.

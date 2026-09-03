## Context

The repository has schemas (`autocut/core/config.py`, `autocut/core/manifest.py`), a progress event type and CLI stubs, but no behavior. SPEC.md sections 7.1 and 9 and ADR 3 fix the shape of ingest: ffprobe only, no exiftool, capability based classification, telemetry as pluggable adapters, manifest as the project file. Measured facts in SPEC.md section 4 define the fixtures: DJI Mini 2 telemetry is an embedded `mov_text` track, Action 4 ships `.LRF` proxies, Xiaomi verticals use rotation side data.

## Goals / Non-Goals

**Goals:**

- One `ffprobe` call per file, parsed into a typed `ProbeResult`.
- Telemetry adapters with a two-method interface (`detect`, `parse`) so GoPro GPMF can be added later without touching ingest.
- Classification as a pure function of probe result plus telemetry kind plus overrides, unit testable without files.
- Ingest runs files in a process pool sized on physical cores; probing and telemetry extraction are subprocess bound.

**Non-Goals:**

- Frame decoding, metrics, segmentation and cache storage of arrays (next change).
- GPMF parsing, Insta360 `.insv` data tracks.
- Reverse geocoding.

## Decisions

**ffprobe invocation.** `ffprobe -v error -print_format json -show_format -show_streams <file>`. Rotation is read from `side_data_list[].rotation` on the video stream, with fallback to the legacy `tags.rotate`. GPS is parsed from format tag `location` in ISO 6709 form (`+39.9664+9.6850/`). Alternative considered: exiftool, rejected because every needed field is present in ffprobe output on all three current devices.

**Telemetry adapter interface.** `TelemetryAdapter` protocol with `kind`, `detect(probe, path) -> bool` and `parse(path) -> TelemetrySeries`. Adapters are tried in a fixed list: embedded SRT, sidecar SRT. The DJI cue parser is shared by both adapters and is a regex over `key value` pairs so that new fields in future firmware do not break parsing. Extraction uses `ffmpeg -v error -i <file> -map 0:s:<idx> -f srt -` with the subtitle index taken from the probe, so no video decoding happens.

**Classification order.** Telemetry kind first, then make and model tags, then Android and Apple manufacturer tags, then camera manufacturer tags, then fps and aspect heuristics, then filename pattern. Each rule returns the class and a signal name. Overrides run last and win. Alternative considered: a scoring model with weights; rejected as untestable and opaque for a five class problem.

**Cache key.** `blake2b` over size, mtime as integer nanoseconds, first 1 MB and last 1 MB, hex digest truncated to 32 characters. Path excluded so copies share keys (ADR 6). The full-file hash was rejected for cost.

**Chronological sort.** Sort key is `(creation_time or mtime, path)`. `creation_time` is parsed as UTC; devices write UTC in the current footage. Timezone handling for display is deferred to the report.

**Parallelism.** `concurrent.futures.ProcessPoolExecutor` with `max_workers = config.analysis.workers or physical cores`. Each worker returns a `SourceFile`; the parent assigns order and writes the manifest. Progress events are emitted from the parent as futures complete.

**Manifest additions.** `SourceFile` gains `class_signal: str`, `telemetry_summary: TelemetrySummary | None`, `error: str | None`, `subtitle_streams: list[StreamInfo]`, `data_streams: list[StreamInfo]`. `MANIFEST_SCHEMA_VERSION` stays at 1 because no manifest has been written yet.

## Risks / Trade-offs

- [ffprobe output differs between ffmpeg 6 on macOS Homebrew and ffmpeg 8 on Linux] → parse defensively, test the parser on captured JSON fixtures from both, keep raw tags in the cache for debugging.
- [Creation time in local time on some devices] → record the raw string and the parsed UTC value; order is still consistent within one device, cross device ordering may be off by the zone offset until a per-folder offset option exists.
- [Process pool and subprocess on macOS use spawn] → keep worker functions module level and picklable; test on Linux, note macOS check in tasks.
- [Filename heuristics misclassify] → filename is the weakest signal and the deciding signal is recorded, so the report can show why.

## Open Questions

None that change the specs. Timezone handling for creation time is deferred to the report change.

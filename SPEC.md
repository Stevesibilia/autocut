# AutoCut specification

AutoCut selects, trims, orders and normalizes short clips out of a folder of raw vacation footage (drone, action cam, phone, camera) so they can be dropped into CapCut desktop in one go. It also proposes a soundtrack prompt and cuts the clips to the beat once the track exists. It is not an editor.

This document supersedes `specifiche-autocut.it.md`, the original Italian draft. Every decision taken during the 2026-09-03 review is folded in here. Architecture decisions with trade-offs live in `docs/adr/`.

## 1. Goal

Given one or more folders with tens or hundreds of raw video files, produce an output folder of sub-clips that are already screened, cut, ordered and normalized, ready for a single drag and drop into CapCut.

The problem is screening, not editing. Watching 150 files to find the 3 good seconds in each is the work AutoCut removes. Beat sync fine-tuning, transitions, titles and the final export stay in CapCut.

**Success criterion.** From about 150 raw files of one vacation, one pass produces a `_selects/` folder with 30 to 50 numbered clips, all usable, that imported in alphabetical order into CapCut give a sensible timeline without manual reordering.

## 2. Non-goals

- **No editing.** No timeline, no rendering of the final edit.
- **No transitions, titles, subtitles or effects.**
- **No music synthesis inside the app.** The app produces a prompt for an external generator (Suno by default) and consumes the resulting track.
- **No collaboration.** Single user, single machine at a time.
- **No Windows support.** Linux and macOS only.

## 3. Context of use

- **User.** One technically competent person who reads Python and uses a CLI, and who also wants a desktop GUI as the final deliverable.
- **Machines.** Development on Linux (AMD Ryzen with VAAPI capable iGPU, no NVIDIA). Production use on an Apple Silicon MacBook (M4, 24 GB), where CapCut also runs. The output folder moves between machines through a share or external disk.
- **Current gear.** DJI Mini 2, DJI Osmo Action 4, Xiaomi Redmi Note 13 Pro 5G, Fujifilm camera used mostly for photos. Gear will change over time, so nothing in the design may depend on a specific model. Per-model knowledge lives in data (adapters and config), never in control flow.
- **Color profiles.** Standard profiles everywhere today. LUT support exists as a hook, not as a priority.
- **Soundtrack.** Generated externally. Two-pass flow: select clips, generate prompt, user generates the track, track comes back for beat sync.
- **Downstream editor.** CapCut desktop.

## 4. Observed footage facts

Measured on the private test set (Sardinia 2025). They drive defaults and must be re-checked when gear changes.

| Device                      | Container and codec | Resolution and fps | Pixel format     | Telemetry                                                                                                                 | Proxy                                                  | GPS                                               |
| --------------------------- | ------------------- | ------------------ | ---------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------- |
| DJI Mini 2                  | MP4, H.264          | 3840x2160 at 25    | 8-bit SDR bt709  | embedded `mov_text` subtitle stream, 1 Hz, with ISO, shutter, EV, GPS, relative height `H`, horizontal and vertical speed | none                                                   | format tag `location` and per-second in telemetry |
| DJI Osmo Action 4           | MP4, HEVC           | 1920x1080 at 50    | 10-bit SDR bt709 | proprietary `djmd` and `dbgi` data streams, not parsed                                                                    | `.LRF` sidecar, H.264 1280x720 at 25, about 5x smaller | none                                              |
| Xiaomi Redmi Note 13 Pro 5G | MP4, H.264          | 1920x1080 at 30    | 8-bit SDR bt709  | none                                                                                                                      | none                                                   | format tag `location`, make and model tags        |
| Fujifilm                    | untested            | untested           | untested         | none expected                                                                                                             | none                                                   | untested                                          |

Consequences already baked in:

- **Three frame rate families** coexist (25, 30, 50). Normalization must not assume 30.
- **The DJI Mini 2 does not write sidecar `.SRT` files.** Telemetry is inside the MP4 as a subtitle track and is extracted with `ffmpeg -map 0:s:0 -f srt`.
- **The Action 4 writes `.LRF` proxies**, not `.LRV`. Proxy discovery must match both extensions by stem.
- **Vertical phone clips are stored landscape** with a `rotation -90` side data entry. Orientation is read from side data, never from raw width and height.
- **Very short phone clips exist** (under 2 s). Head and tail trimming must be per source or they vanish.
- **Reflex support is untested.** The class exists in code; behavior on real files is best effort until footage is available.

## 5. Architecture

Three layers, developed in this order:

```text
autocut/
├── core/   # library: ingest, analysis, scoring, selection, soundtrack, export
├── cli/    # Typer command line (Phase 1)
└── gui/    # PySide6 desktop app (Phase 2)
```

`core/` never imports from `cli/` or `gui/` and never prints. It reports progress and events through callbacks or generators so both front ends can consume the same API. The GUI is a consumer of the core API, not a rewrite.

**Phase 1, CLI.** Validates selection quality on real footage before any GUI work. Must be useful on its own.

**Phase 2, GUI.** Makes the process steerable and correctable by hand, because no scoring will be right 100% of the time. The GUI is a committed deliverable, not an option.

### 5.1 Providers

Anything that can be done locally or through a paid service sits behind a provider interface with a local implementation that always exists:

- **Frame embeddings** for similarity. Local CLIP or SigLIP only. No cloud provider planned, the local model is cheap and good enough.
- **Semantic tagging, aesthetic score, captions.** Local zero-shot CLIP as baseline. Optional cloud vision model through OpenRouter, one 320 px JPEG per segment. Cloud is used when a key is present and not disabled.
- **Prompt refinement.** Template generator as baseline. Optional LLM through OpenRouter.
- **Music.** `MusicProvider` interface. The first implementation is "manual Suno": write the prompt, the user pastes it and brings the track back. API-driven providers can be added later without touching selection or sync.
- **Reverse geocoding.** Online with on-disk cache. No offline dataset.

Data sent to cloud providers is limited to downscaled frames and derived signals (tags, energy curve, place names, time of day). Full files never leave the machine. See ADR 4.

## 6. Technology stack

### 6.1 Core

- **Python 3.11 or newer.** Development runs on 3.14 on the Linux host, wheels for all core dependencies exist. CI tests 3.11, 3.12 and 3.14.
- **ffmpeg and ffprobe** as external binaries invoked through `subprocess`. No wrapper library. Frame sampling uses an ffmpeg pipe to raw RGB into NumPy, with `-hwaccel auto` so VAAPI on Linux and videotoolbox on macOS are used when available. PyAV is not used. See ADR 2.
- **NumPy and OpenCV (headless)** for frame metrics.
- **PySceneDetect** for intra-file shot splitting.
- **librosa** for beat tracking and BPM.
- **Pydantic** for config and manifest schemas.
- **Typer and Rich** for the CLI.
- **httpx** for OpenRouter calls.
- **keyring** for API key storage from the GUI.

Optional extras in `pyproject.toml`:

- `autocut[ai]`: torch, open_clip, plus the aesthetic predictor weights loader.
- `autocut[gui]`: PySide6.
- `autocut[dev]`: pytest, ruff, mypy, pre-commit.

`exiftool` is not a dependency. Every field needed so far is exposed by ffprobe.

### 6.2 GUI

PySide6 (Qt). The core is Python, Qt gives native filesystem access, thumbnail grids and video playback with `QMediaPlayer`, and the app can be bundled with PyInstaller. Electron is excluded. Flet or a FastAPI plus `pywebview` app are fallbacks only if PySide6 packaging or playback fails badly.

Hover scrubbing on 4K originals is not attempted. The GUI scrubs on thumbnail sprite strips produced during analysis.

## 7. Pipeline

### 7.1 Ingest

Recursive scan of the source folders.

- **Accepted extensions.** `.mp4`, `.mov`, `.mkv`, `.avi`, `.m4v`, `.insv`. Proxy extensions `.lrv` and `.lrf` are never analyzed as sources; they are attached to the file with the same stem.
- **Probe.** `ffprobe` JSON for duration, resolution, fps, codec, pixel format, bit depth, color transfer, rotation side data, `creation_time`, format tags including `location`, make and model, and the list of subtitle and data streams.
- **Proxy discovery.** If a `.lrv` or `.lrf` with the same stem exists, analysis runs on it and the full file is used only for export. Logged per file, disabled with `analysis.use_proxies = false`.
- **Telemetry adapters.** A telemetry source is detected per file by capability, not by brand. Adapters implemented in order:
  1. DJI embedded subtitle stream (`mov_text`, 1 Hz) with height, speed, GPS, ISO, shutter.
  2. DJI sidecar `.SRT` with the same fields for models that write it.
  3. GoPro GPMF data stream, only when a GoPro appears.
     Unknown telemetry formats are ignored, the file falls back to image metrics.
- **Source classification.** Each file gets a class `drone`, `actioncam`, `phone`, `reflex` or `generic`. The class is derived from signals: telemetry type found, make and model tags, fps, aspect ratio and rotation, and filename pattern as a weak hint. It is overridable per folder glob and per file in `autocut.toml`. See ADR 3.
- **Chronological order.** Global sort on `creation_time`, fallback on mtime. Mixed sources produce one coherent timeline.

Per-class analysis rules:

- **actioncam.** Sharpness on the center 60% of the frame, fisheye edges are ignored. High fps is a natural slow motion candidate.
- **phone.** Vertical clips detected from rotation side data and handled explicitly in export.
- **reflex.** Stricter quality thresholds and less aggressive rejection, the material is little and already good. Untested until footage exists.
- **drone.** Altitude and speed from telemetry drive takeoff and landing rejection.

### 7.2 Segmentation

PySceneDetect `ContentDetector` splits files with several shots into separate candidates. Segments shorter than `selection.min_segment_seconds` (default 1.5) are dropped.

### 7.3 Analysis and scoring

Sampled decoding only: 2 fps, long side 320 px, through the ffmpeg pipe. Full decode of 4K is never done.

| Metric       | Method                                                    | Purpose                                                |
| ------------ | --------------------------------------------------------- | ------------------------------------------------------ |
| Sharpness    | Laplacian variance, center crop for actioncam             | Reject blur and misfocus                               |
| Exposure     | Share of pixels clipped at 0 and 255                      | Reject under and over exposure                         |
| Motion       | Mean optical flow magnitude, or absolute frame difference | Separate cinematic motion from static shots and shakes |
| Stability    | Standard deviation of the motion vector over time         | Reject unstable gimbal and jerky corrections           |
| Colorfulness | Hasler and Süsstrunk metric                               | Reward sunsets and saturated landscapes                |

The composite score is a weighted mean with weights in `autocut.toml`. Weights are found by iterating on real footage, so they are never hardcoded.

Rejection rules run before scoring:

- **Low altitude** from telemetry, below `rules.drone.min_height_m`: takeoff or landing.
- **No motion** for the whole segment: parked drone or forgotten camera.
- **High motion with low stability**: shaky footage.
- **Head and tail trim** per class: drone 1.0 s, actioncam 1.0 s, phone 0.3 s, reflex 0.5 s, generic 0.5 s. Segments that fall under the minimum duration after trimming are dropped with the reason logged.

Analysis also writes one thumbnail per segment and, when `analysis.sprites = true`, a 320 px sprite strip for GUI scrubbing.

### 7.4 Best window and selection

For each surviving segment, a sliding window search finds the sub-window of target duration with the highest mean score. Default target 3 s. The manifest stores the segment bounds and the best window center, not a fixed final duration, so that beat sync can later grow or shrink the window around the center within the segment. See ADR 5.

Global constraints:

- **Max clips per file** by class: drone 1, actioncam 3, phone 1, reflex 2, generic 1. Segments of the same file compete, the cap applies at selection.
- **Max total clips**, configurable.
- **Minimum share per class**, so a mixed vacation does not become an all-aerial edit.

#### Deduplication and diversity

This is a central requirement, not polish. Selection by score alone produces ten near identical beach shots.

Selection is greedy with a similarity penalty: at each step pick the clip maximizing `score - lambda * max(similarity to already selected)`. `lambda` is configurable and exposed as the diversity slider in the GUI. Maximal Marginal Relevance is the same idea and an acceptable implementation.

Similarity combines signals, each switchable:

| Signal           | Method                                            | Captures                             |
| ---------------- | ------------------------------------------------- | ------------------------------------ |
| Visual, semantic | Cosine distance between CLIP or SigLIP embeddings | Same scene from different angles     |
| Visual, fallback | Perceptual hash plus color histogram              | Coarse similarity without models     |
| Spatial          | GPS distance                                      | Shots from the same spot             |
| Temporal         | Timestamp distance                                | Consecutive shots of the same moment |
| Motion           | Motion profile similarity                         | Three identical left to right pans   |

Additional constraints: max clips per visual cluster (default 2 to 3), minimum temporal distance between consecutive clips in the final order, and balance across semantic categories when tags are available.

The no-model fallback (hash, histograms, GPS, time) must work acceptably. Models improve the result but are never a prerequisite.

### 7.5 Soundtrack prompt

After selection, AutoCut analyzes the chosen clips and writes a prompt for the music generator. Music is built around the video, not the other way round.

#### Order of operations

Beat sync needs a BPM, but the track does not exist yet. The loop is broken like this:

1. AutoCut proposes a BPM from the selected material and writes it into the prompt.
2. The user generates the track.
3. The track comes back, AutoCut measures the real BPM with librosa. Suno does not guarantee the requested BPM, so beyond a tolerance the app warns and offers to requantize on the measured BPM.
4. Beat cut and export.

The proposed BPM is derived from mean clip duration and material energy, chosen so typical durations fall on whole beats. It is always editable.

#### Input signals

All available from analysis: total duration and clip count, energy profile over the sequence, dominant semantic tags, dominant palette and color temperature, time of day and place from GPS, share of each source class, and captions when the cloud vision provider is on. Captions make the prompt specific instead of generic.

#### Output format

`suno-prompt.md` in the output folder with three copyable blocks: **Title**, **Description**, **Structure**. Lowercase, instrumental only. Suno custom mode is assumed: Description goes in the style field, Structure in the lyrics field, so both blocks are deliverables.

Description rules (style field, about 200 characters):

- **Comma separated tags**, never sentences.
- **Priority order**: genre or era, instruments with a specific adjective (`sweeping strings`, not `strings`), mood, production, BPM.
- **4 to 7 descriptors.** More degrades the result.
- **No repeated concept** in different words.
- **Always ends** with `no vocals, instrumental`.

Structure rules (lyrics field, bracketed tags):

- **One tag per line.**
- **One modifier per tag**, modifier before the section word, no commas inside brackets. `[slow intro]` and `[dark intro]` on two lines, never `[slow, dark intro]`.
- **Allowed section words only**: `intro`, `verse`, `verse 1`, `verse 2`, `verse 3`, `pre-chorus`, `chorus`, `bridge`, `solo`, `break`, `drop`, `build`, `transition`, `outro`, `end`.
- **3 to 6 tags per section**, covering different dimensions (energy, instrument, mood, tempo).
- **No vocal tags.**
- **Production adjectives** (`filtered`, `sidechained`, `punchy`) belong in Description next to their instrument, not in Structure.
- **Every instrument named in Description** appears as a modifier in at least two Structure tags.
- **Last line is always** `[end]`.

The energy profile of the edit maps to the structure arc: calm opening on the first clips, development, peak on the clips with highest score and motion, resolution. Not a generic arc, the actual one of this edit.

#### Implementation

Two levels:

- **Template generator**, always available. A mapping table from (dominant tags, color mood, energy) to (genre, instrumentation, BPM) plus a template based structure generator. The genre table lives in `autocut.toml` under `soundtrack.genres` with shipped defaults, so the user tunes taste without code changes.
- **LLM refinement**, optional through OpenRouter. Takes the structured signals and captions and writes a more specific prompt.

Both paths go through formal validation before display: Description length, one tag per line, no commas in brackets, valid section words, `[end]` present, no vocal tags. A malformed prompt produces wrong music and the error is invisible by eye.

The app generates 3 to 5 variants with slightly different mood or instrumentation.

### 7.6 Beat sync

- **Beat tracking.** `librosa.beat.beat_track()` on the provided track gives BPM and beat positions. The user can override BPM, because Suno tracks often have a declared BPM and detection sometimes halves or doubles it.
- **Durations on the beat.** Each clip is cut to a whole number of beats from the allowed set `{2, 4, 8}` beats. At 120 BPM that is 1, 2 and 4 s. The multiple follows the score: best clips get longer durations. A clip whose segment is too short for the chosen multiple drops to the next smaller one.
- **Window placement.** The final window is centered on the stored best window center and clamped to the segment bounds.
- **Alternation**, configurable: alternate long and short durations to give the edit rhythm.

Result: clips in a row already fall on beats, CapCut auto beat sync has little or nothing to fix.

### 7.7 Export

ffmpeg cut, two modes:

- **Precise** (default): re-encode with `libx264 -crf 18`, 8-bit `yuv420p`, frame exact. Hardware encoders (`h264_videotoolbox`, `h264_vaapi`) are an opt-in for speed at the cost of cross-platform identical output.
- **Fast**: `-c copy` aligned to the nearest keyframe. For a first exploratory look only, documented as imprecise on durations.

Transformations:

- **Audio removal** (`-an`) by default. Drone audio is rotor noise. Switchable off per class, family clips keep ambient audio when wanted.
- **Frame rate normalization.** `export.fps = "auto"` picks the dominant fps among selected clips (25 on the current footage). Clips converted from a non-multiple fps are flagged in the report. Explicit `--fps` overrides.
- **Resolution normalization.** Downscale to `export.max_resolution` (default 3840x2160), never upscale.
- **Pixel format normalization** to 8-bit `yuv420p`. 10-bit passthrough is an option.
- **Slow motion.** Automatic when the source fps is at least twice the target and the class is `actioncam` (Action 4 at 50 fps to 25 fps target gives clean 2x). Off for other classes unless forced.
- **Vertical clips.** Three strategies: exclude from selection (default), blur padded sides, center crop. The choice is explicit and visible in the report. Silent mixing of vertical and horizontal is the kind of error found only in CapCut.
- **LUT per class** through `lut3d`, with a class to `.cube` mapping in config. A hook only until log profiles are used.
- **Lens correction** for actioncam through `lenscorrection`, optional.

### 7.8 Output naming

CapCut imports in alphabetical order, so the filename carries chronology:

```text
{index:03d}_{date}_{class}_{tag}_{duration}s.mp4

012_20260812_drone_sunset_4.0s.mp4
013_20260812_phone_family_2.0s.mp4
014_20260812_actioncam_snorkeling_2.0s.mp4
015_20260813_reflex_detail_4.0s.mp4
```

Output folder:

```text
output/
├── _selects/         # chosen clips, numbered
├── _rejects/         # rejected clips, optional
├── thumbs/           # per segment thumbnails and sprite strips
├── report.html       # visual review
├── manifest.json     # full analysis state, project file
├── suno-prompt.md    # prompt for the music generator
└── beatmap.txt       # beat positions, for reference in CapCut
```

### 7.9 Review report

`report.html` is self contained and opens in a browser: grid with thumbnail, filename, duration, composite score, per metric scores, class, rejection reason. It lets the user delete wrong picks in two minutes before importing. The GUI replaces it in Phase 2, the CLI keeps producing it.

## 8. AI modules

Models are allowed and in some places clearly better than classic heuristics. Rules:

- **Graceful degradation.** The app works, with lower quality, without models, GPU or network.
- **Individually switchable** in config.
- **Cloud is optional and opt-out.** Cloud features turn on when `OPENROUTER_API_KEY` is present and turn off with `--no-cloud` or `providers.cloud = false`.

Modules in order of value over complexity:

1. **CLIP or SigLIP embeddings**, one frame per segment, local. The enabler for everything below and the first to implement.
2. **Semantic similarity for deduplication.** The best similarity signal by far.
3. **Semantic tagging.** Local zero-shot against a label set (`aerial`, `sunset`, `beach`, `mountain`, `people`, `food`, `city`, `underwater`, `indoor`, `street`), or cloud vision model. Feeds the filename tag, category balancing and the soundtrack prompt.
4. **Captions**, cloud vision model only. One sentence per selected clip, feeds the soundtrack prompt.
5. **Aesthetic scoring.** Predictor on CLIP embeddings (LAION weights) locally, or the cloud model's judgment.
6. **Face detection** (MediaPipe or InsightFace). Family scenes have value no sharpness metric sees. Raises the score, handled as a separate rule. Also protects deduplication: similar frames with different people are not duplicates.
7. **LLM prompt refinement**, through OpenRouter, output always validated.
8. **Narrative ordering by LLM**, low priority. Group by place from GPS instead of pure chronology.

## 9. Data model

`manifest.json` is the single source of truth and the project file. For each analyzed segment: source path, proxy path if any, class, in and out points, best window center, all raw metrics, composite score, outcome (selected or rejected) with reason, tags, caption, embedding reference, exported path. Opening a manifest in the GUI restores the full review state. The schema is versioned.

**Analysis cache** is global, in the platform cache directory (`~/.cache/autocut/` on Linux, `~/Library/Caches/autocut/` on macOS). The key is path, size, mtime and a hash of the first and last 1 MB. Per source file, one `.npz` with metric arrays and embeddings plus a JSON with probe and telemetry. Re-running on the same footage with different weights is instantaneous, in any project. See ADR 6.

## 10. CLI

```bash
# first pass
autocut analyze    ./footage --out ./edit-sardinia
autocut select     ./edit-sardinia --max-clips 40 --duration 3.0 --diversity 0.6
autocut soundtrack ./edit-sardinia --variants 3
autocut report     ./edit-sardinia

# generate the track externally, then second pass
autocut sync       ./edit-sardinia --audio track.mp3
autocut export     ./edit-sardinia --no-audio
```

Commands are separate and re-runnable, reading and writing the same manifest. Tuning means running `select` twenty times over one `analyze`.

`autocut sync` without `--bpm` measures the real BPM and compares it to the one proposed by `soundtrack`, warning on mismatch. `--bpm` wins when given.

`autocut run` chains the first pass. Configuration comes from `autocut.toml` with command line overrides. All CLI output is in English.

## 11. GUI

Five screens with back and forward navigation. All strings in English.

1. **Project and sources.** Drag and drop source folders, output folder, profile (drone, family, mixed). Open an existing manifest.
2. **Analysis.** Progress with current file, estimated time left, cancel. Runs in a worker, the UI never blocks. Interruptible and resumable.
3. **Review.** The central screen. Thumbnail grid by chronology or score, hover scrubbing on sprite strips, keep and reject by click and keyboard, in and out adjustment with preview, filters by tag, class and score range, scoring weight sliders with live reordering, the diversity slider in the foreground, a similar-groups view where one click swaps the algorithm's pick, and a counter of selected clips and total duration.
4. **Soundtrack.** First the generated prompt in three blocks with copy buttons, variant browsing, editable BPM that regenerates, mood controls (calmer or more energetic, cinematic or intimate), hand editing with live validation. Then track upload, waveform with beats, requested versus measured BPM with warning, duration strategy.
5. **Export.** LUT per class, target fps and resolution, vertical strategy, slow motion, audio removal. Progress, then open the result folder.

Cross cutting: no long operation on the UI thread, state saved continuously to the manifest, API keys stored in the OS keychain through `keyring`.

## 12. Performance

Target: 100 GB of 4K analyzed in under 30 minutes on the M4 MacBook.

Levers, by impact:

- **Proxies** (`.lrv`, `.lrf`) when present. Free 5x.
- **Sampled decoding**, 2 fps at 320 px. Note that on HEVC with long GOPs, seeking to 2 fps still decodes most frames, so hardware decode matters more than the sample rate.
- **Hardware decode**, chosen once per run rather than per file and verified by decoding one frame of the first file, with a single demotion to software for the whole run if that fails. `analysis.hwaccel` accepts `auto`, `off`, `vaapi` and `videotoolbox`. `auto` selects videotoolbox on macOS and software elsewhere; it never selects CUDA, which is what ffmpeg's own `-hwaccel auto` picked on the AMD development host before failing on every file.

  Hardware decode is a lever only where it measures as one. On the AMD iGPU it is not: sampling one 4K clip at 2 fps measured 3.9 s in software against 9.0 s through VAAPI, and 5.7 s with a full GPU filter chain. At this sample rate most of the work is skipping frames rather than decoding them, and every decoded surface still crosses back to system memory, so VAAPI has to be asked for by name. The macOS figure is the one that matters for the 100 GB target and is still to be measured on the M4.

- **Parallel files** with `ProcessPoolExecutor` sized on physical cores.
- **Global cache.**

## 13. Packaging and distribution

The final product is a packaged macOS app with a `.dmg`, built with PyInstaller. Cross building from Linux is not possible, so the build runs on a GitHub Actions macOS Apple Silicon runner on tags and can also be run by hand on the MacBook with `make dmg`.

The bundle includes torch and a static ffmpeg. Model weights are downloaded on first run into the app support directory. The app is unsigned for now, with right-click Open instructions; notarization is a later decision. A Linux AppImage is a nice to have. See ADR 7.

## 14. Testing

- **Synthetic fixtures**, committed. Generated by `scripts/make_fixtures.py` with ffmpeg test sources: sharp, blurred, over and under exposed, static, shaky, multi-shot, vertical with rotation side data, 10-bit HEVC, and a clip with an injected DJI style telemetry subtitle stream. Small, deterministic, public safe.
- **Private fixtures**, never committed. Cut from real footage into `tests/fixtures/private/` (gitignored). Tests using them skip when the folder is empty. Real folder integration tests run against `AUTOCUT_REAL_FOOTAGE` when set. See ADR 8.
- **Unit tests** on metrics with expected values per fixture.
- **ffmpeg command tests** that check the generated argument list without running it.
- **End to end** on the synthetic folder, checking exact exported durations in precise mode.
- **Beat quantization**: at a known BPM every duration is a whole beat multiple within one frame.
- **Deduplication**: near identical fixtures keep at most the configured count, and keep the best score.
- **Prompt validator**: malformed prompts (commas in brackets, several tags per line, invented section words, vocal tags, Description too long) are rejected with the right error.

Tests run in Docker on Linux (`compose.yaml`, `python:3.12` image with ffmpeg). Nothing is installed on the host beyond the project venv.

## 15. Roadmap

- **M0, foundation.** This spec, ADRs, repository skeleton, config and manifest schemas, Docker dev setup, CI, synthetic fixture generator.
- **M1, ingest and analysis.** Scan, probe, proxy discovery, telemetry adapters (DJI embedded subtitle first), classification, classic metrics, manifest, global cache. Output: `report.html` only. Verifies scoring on real footage before building on it.
- **M2, selection and export.** Best window, rejection rules, deduplication with classic signals, cutting, normalization, naming. The tool is useful from here.
- **M3, embeddings and diversity.** CLIP or SigLIP, semantic similarity, greedy selection with penalty, tagging (local and cloud), captions.
- **M4, soundtrack.** Template prompt, validation, variants, optional LLM refinement. Beat tracking, beat durations, BPM check, `beatmap.txt`.
- **M4b, remaining AI.** Aesthetic scoring, face detection.
- **M5, GUI.** Five screens on the existing core.
- **M6, packaging.** macOS `.dmg` on CI, first run model download.

Stopping after M2 to use the tool on real footage before continuing is expected. Scoring weights are tuned on real material and every later milestone builds on that tuning.

## 16. Open items

- **Fujifilm footage** is needed to validate the `reflex` class. Until then it is best effort.
- **Genre defaults** in `soundtrack.genres` are placeholders until the user tunes them.
- **Action 4 gyro** in `djmd` is unparsed. Shake detection relies on image metrics. Revisit only if results are poor.
- **Insta360 `.insv`** is accepted by extension but untested. Requiring an MP4 export from Insta360 Studio is acceptable.

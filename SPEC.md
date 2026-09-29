# AutoCut specification

AutoCut selects, trims, orders and normalizes short clips out of a folder of raw vacation footage (drone, action cam, phone, camera) so they can be dropped into CapCut desktop in one go. It also proposes a soundtrack prompt and cuts the clips to the beat once the track exists. It is not an editor.

This document supersedes the original Italian draft, which git history keeps. Every decision taken during the 2026-09-03 review is folded in here. Architecture decisions with trade-offs live in `docs/adr/`.

## 1. Goal

Given one or more folders with tens or hundreds of raw video files, produce an output folder of sub-clips that are already screened, cut, ordered and normalized, ready for a single drag and drop into CapCut.

The problem is screening, not editing. Watching 150 files to find the 3 good seconds in each is the work AutoCut removes. Beat sync fine-tuning, transitions, titles and the final export stay in CapCut.

**Success criterion.** From about 150 raw files of one vacation, one pass produces a `_selects/` folder with 30 to 50 numbered clips, all usable, that imported in alphabetical order into CapCut give a sensible timeline without manual reordering.

## 2. Non-goals

- **No editing.** No timeline, no transitions or titles. A hard cut render of the edit with its track is an optional output for edits that need nothing more; anything past that stays in CapCut.
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

`core/` never imports from `cli/` or `gui/` and never prints. It reports progress and events through callbacks or generators so both front ends can consume the same API. The GUI is a consumer of the core API, not a rewrite. `core/pipeline.py` runs ingest, analysis, embedding, tagging and description in the one order both front ends need, so the CLI's `analyze` command and the GUI's analysis stage cannot drift apart; a cancelled run stops there before embedding, tagging or describing, in both.

**Phase 1, CLI.** Validates selection quality on real footage before any GUI work. Must be useful on its own.

**Phase 2, GUI.** Makes the process steerable and correctable by hand, because no scoring will be right 100% of the time. The GUI is a committed deliverable, not an option.

### 5.1 Providers

Anything that can be done locally or through a paid service sits behind a provider interface with a local implementation that always exists:

- **Frame embeddings** for similarity. Local CLIP or SigLIP only. No cloud provider planned, the local model is cheap and good enough.
- **Semantic tagging, aesthetic score, captions.** Local zero-shot CLIP as baseline. The aesthetic score is local by default when `providers.aesthetic` is on (the bundled LAION head, §8 item 5), and a cloud judgment replaces it. Optional cloud vision model through OpenRouter, one 320 px JPEG per segment, one request per segment, cached forever per model and prompt version. Cloud is used when `providers.cloud` is true, a key is available and `--no-cloud` was not passed; any of the three disables every call in the run and the CLI says which. Built in M3.
- **Prompt refinement.** Template generator as baseline. Optional LLM through OpenRouter.
- **Music.** `MusicProvider` interface. The first implementation is "manual Suno": write the prompt, the user pastes it and brings the track back. API-driven providers can be added later without touching selection or sync.
- **Reverse geocoding.** Online with on-disk cache. No offline dataset.

Data sent to cloud providers is limited to downscaled frames and derived signals (tags, energy curve, place names, time of day). Full files never leave the machine. See ADR 4.

The vision request carries the 320 px thumbnail, the fixed prompt and the model id, and nothing else: no file name, no path, no timestamp, no position, no telemetry, no segment id. The payload is built in one function so that boundary has one place to be audited, and a unit test asserts the body against it.

The key comes from `OPENROUTER_API_KEY` or from the OS keychain entry `autocut/openrouter`, the environment winning so a script can set it for one run. `autocut key set` prompts for one without echoing, or reads it from standard input with `--stdin` for a script, and `autocut key clear` removes it. There is no option to pass the key as an argument: an argument is readable in `ps` and in `/proc/*/cmdline` by any other local user and lands in the shell history. The key is never written to `autocut.toml`, the manifest, the cache or a log line, and `autocut doctor` reports its presence and the configured model, never its value.

Failures are bounded twice. A request retries on 429 and 5xx with backoff 1, 2, 4, 8 s up to `providers.max_retries`, and any other 4xx fails at once. `providers.max_failures` consecutive failures stop the describe step for the run, so an outage costs about that many requests rather than one per segment. A failure is recorded on the segment and the run completes.

## 6. Technology stack

### 6.1 Core

- **Python 3.12 or newer.** Development runs on 3.14 on the Linux host, wheels for all core dependencies exist. CI tests 3.12, 3.13 and 3.14.
- **ffmpeg and ffprobe** as external binaries invoked through `subprocess`. No wrapper library. Frame sampling uses an ffmpeg pipe to raw RGB into NumPy, with hardware decoding chosen by AutoCut rather than by ffmpeg's own `-hwaccel auto` (see Hardware decode in §12). PyAV is not used. See ADR 2. Every external call has its own timeout in the `[timeouts]` table of `autocut.toml` (`ffprobe_s`, `hwaccel_probe_s`, `sample_read_s`, `export_clip_s`, `montage_part_s`, `concat_s`, `audio_decode_s`, `telemetry_extract_s`, `version_check_s`), so a hung process fails the one file or clip it was working on rather than the run.
- **NumPy and OpenCV (headless)** for frame metrics.
- **PySceneDetect** for intra-file shot splitting, behind the optional `scenedetect` extra (see §7.2 and ADR 11).
- **librosa** for beat tracking and BPM.
- **Pydantic** for config and manifest schemas.
- **Typer and Rich** for the CLI.
- **httpx** for OpenRouter calls.
- **keyring** for API key storage from the GUI.

Optional extras in `pyproject.toml`:

- `autocut[ai]`: torch 2.14, torchvision 0.29 and open_clip_torch 3.3, plus the bundled LAION aesthetic head and a second, OpenAI ViT-B/32 tower for it. torch and torchvision are pinned as a pair because every torchvision release pins one exact torch version. The vision model is `ViT-B-32/laion2b_s34b_b79k`, 512 dimensions and about 350 MB, downloaded once into the platform cache directory under `models/` so later runs work offline. The aesthetic tower, `ViT-B-32-quickgelu/openai`, is another 350 MB downloaded the same way, and only when `providers.aesthetic` is on. On Linux without an NVIDIA GPU, install torch from `https://download.pytorch.org/whl/cpu`: the PyPI wheel depends on the whole CUDA 13 stack and costs several gigabytes for nothing.
- `autocut[gui]`: PySide6.
- `autocut[dev]`: pytest, ruff, mypy, pre-commit.

`exiftool` is not a dependency. Every field needed so far is exposed by ffprobe.

`autocut doctor` reports what the machine provides, before a run rather than during one: the ffmpeg and ffprobe versions, the decoder `auto` would choose and whether it verified against a sample file, whether the `ai` extra imports, the compute device embeddings would use, whether the model weights are already downloaded, whether an OpenRouter key is available from the environment or the keychain, and the cache directory with its size. `--json` prints the same facts for scripts and the GUI. It exits non-zero only when ffmpeg or ffprobe is missing, since everything else is optional.

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
- **Source classification.** Each file gets a class `drone`, `actioncam`, `phone`, `reflex` or `generic`. The class is derived from signals: telemetry type found, make and model tags, fps, aspect ratio and rotation, and filename pattern as a weak hint. A frame rate at or above `analysis.high_fps_threshold` (100 by default) classifies an otherwise unrecognized file as actioncam, since that combination only comes from a camera built for slow motion. It is overridable per folder glob and per file in `autocut.toml`. See ADR 3.
- **Chronological order.** Global sort on `creation_time`, fallback on mtime. Mixed sources produce one coherent timeline.

Per-class analysis rules:

- **actioncam.** Sharpness on the center 60% of the frame, fisheye edges are ignored. High fps is a natural slow motion candidate.
- **phone.** Vertical clips detected from rotation side data and handled explicitly in export.
- **reflex.** Stricter quality thresholds and less aggressive rejection, the material is little and already good. Untested until footage exists.
- **drone.** Altitude and speed from telemetry drive takeoff and landing rejection.

### 7.2 Segmentation

The in-memory detector splits files with several shots into separate candidates by default, reusing the frames already sampled for metrics. `analysis.detector = "pyscenedetect"` selects PySceneDetect's `ContentDetector` instead, decoding the file a second time for validation; it needs the optional `scenedetect` extra (`pip install 'autocut[scenedetect]'`) and fails with a message naming it when the extra is missing. When `ffprobe` reports no frame rate for a file, PySceneDetect's minimum scene length falls back to `analysis.fallback_fps` (25). Segments shorter than `selection.min_segment_seconds` (default 1.5) are dropped.

### 7.3 Analysis and scoring

Sampled decoding only: 2 fps, long side 320 px, through the ffmpeg pipe. Full decode of 4K is never done.

| Metric       | Method                                                    | Purpose                                                |
| ------------ | --------------------------------------------------------- | ------------------------------------------------------ |
| Sharpness    | Laplacian variance, center crop for actioncam             | Reject blur and misfocus                               |
| Exposure     | Share of pixels clipped at 0 and 255                      | Reject under and over exposure                         |
| Motion       | Mean optical flow magnitude, or absolute frame difference | Separate cinematic motion from static shots and shakes |
| Stability    | Standard deviation of the motion vector over time         | Reject unstable gimbal and jerky corrections           |
| Colorfulness | Hasler and Süsstrunk metric                               | Reward sunsets and saturated landscapes                |
| Faces        | YuNet face count per frame, percentile over the segment   | Reward people, keep different people apart (§8 item 6) |

The composite score is a weighted mean of rank normalized metrics, with weights in `autocut.toml`. Weights are found by iterating on real footage, so they are never hardcoded.

Normalization is per source class, not across the whole project. Raw metrics are not comparable between classes: action cam segments sampled from 720p proxies scored systematically above drone segments sampled from 4K originals, taking ten of the top twelve places for reasons unrelated to which clip is better. A segment is therefore ranked against the other segments of its own class, and a class with a single segment scores 0.5. Keeping the classes in proportion is the job of the per-class quota in selection, not of the score. The consequence is that scores are comparable within one class of one manifest and meaningless outside it, so the report shows the raw metrics alongside.

`weights.exposure` is 0 by default. On well exposed SDR footage the clipping fraction is effectively zero on every segment, so weighting it ranks on noise; it stays a rejection rule.

Rejection rules run before scoring, in this order, and the first one that fires is the recorded reason:

1. **Too short**, under `selection.min_segment_seconds` after trimming.
2. **Low altitude** from telemetry, below `rules.drone.min_height_m`: takeoff or landing. A takeoff is rarely a separate shot, so segmentation splits each shot where height crosses the threshold before this rule runs.
3. **Clipped**, mean clipping fraction above `rules.max_clipped_fraction`. Exposure is evaluated before the motion rules because a blown out frame is a fact about the picture, while motion describes the camera, and the report should name the defect the viewer can see.
4. **No motion**, mean motion below `rules.min_motion`: parked drone or forgotten camera.
5. **Shaky**, stability below `rules.min_stability` with mean motion at least `rules.shaky_min_motion`. Stability is already motion variability relative to mean motion, so no absolute motion ceiling is needed; the floor keeps a near static wobble reported as no motion instead.

**Head and tail trim** per class runs before all of them: drone 1.0 s, actioncam 1.0 s, phone 0.3 s, reflex 0.5 s, generic 0.5 s.

Thresholds are defaults taken from the measured distribution of the Sardinia set, not guesses: `min_motion` at the pooled 8th percentile of segment motion, `shaky_min_motion` at the 27th, `min_stability` at the 10th percentile of segment stability. `scripts/metric_stats.py` prints that distribution from any manifest, so the defaults can be re-derived on new footage.

Analysis also writes one thumbnail per segment and, when `analysis.sprites = true`, a 320 px sprite strip for GUI scrubbing.

An exception while analyzing one file is recorded as that file's error and never stops the analysis of the others. Ctrl-C stops the run like a cancellation: files finished before it keep their segments, and the command line saves the manifest and exits with status 130.

### 7.4 Best window and selection

For each surviving segment, a sliding window search finds the sub-window of that clip's target duration with the highest mean score. The manifest stores the segment bounds and the best window center, not a fixed final duration, so that beat sync can later grow or shrink the window around the center within the segment. See ADR 5.

**Snap to motion.** Once the window is found, its start may move onto a nearby minimum of the per-frame motion series, so the cut lands where movement stops rather than partway through a pan. The move is allowed within `selection.snap_window_seconds` (0.5 by default), only while the window still fits the trimmed span, and only when the mean score falls by no more than `selection.snap_max_score_loss` (5 percent). The window search already found the frames worth keeping, so the snap is allowed to change where the cut lands and almost nothing else. A static shot has no minimum to land on and is left alone.

#### Clip durations

Forty clips of exactly the same length read as a slideshow. Each selected clip gets its own duration instead, decided after the picks are made, in this order:

- **Base by class**, `selection.duration_by_class`: drone 4.0 s, actioncam 2.0 s, phone 2.5 s, reflex 3.0 s, generic 3.0 s. An aerial needs longer to be read than an action shot.
- **Scaled by score** across `selection.score_duration_range`, 0.8 at score 0 to 1.2 at score 1. Narrow on purpose: the class sets the rhythm and the score only nudges it.
- **Hero bonus.** The top `selection.hero_share` (10 percent) by score is multiplied by `selection.hero_multiplier` (1.5). Four clips in forty get room to breathe.
- **Alternation.** One pass over the chronological order breaks every run of three clips in the same bucket, long being at or above the class base, by scaling the middle one 25 percent towards the other bucket. Buckets are relative to the class base, so a 2.0 s action clip and a 4.0 s drone clip are both ordinary. A hero is never shortened by it; the run is broken with the next clip instead.
- **Optional total.** When `selection.target_total_seconds` is set, one factor scales every duration so the edit lands near it, which keeps the relative rhythm intact. When the bounds put the target out of reach the shortfall is reported rather than clips dropped, because how many clips the edit holds is the user's `max_clips` decision.
- **Clamps** throughout, to `selection.duration_min_seconds` and `selection.duration_max_seconds` (1.5 and 6.0) and to the clip's own trimmed span.

Every clip records which rule settled its length, one of `base`, `hero`, `alternation`, `total`, `clamped` or `override`, and the report shows it. `autocut select --duration <seconds>` sets one length for every clip and turns the whole thing off, which is the behaviour milestone 2 shipped.

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

The visual fallback blends the two signals it names: `similarity.hash_share` (default 0.5) weights the perceptual hash and the rest goes to the color histogram, computed over `similarity.histogram_bins` (default 8) buckets per channel.

Additional constraints: max clips per visual cluster (default 2 to 3), minimum temporal distance between consecutive clips in the final order, and balance across semantic categories when tags are available.

The no-model fallback (hash, histograms, GPS, time) must work acceptably. Models improve the result but are never a prerequisite.

#### Places and visits

The similarity penalty was not enough on the first real edit. Five drone files shot at one spot inside eleven minutes came through as five near identical clips: the spatial and temporal signals both fired, but the perceptual hash split those files across three visual clusters, so the per-cluster cap never applied. Pixels disagreed with the map and the pixels won.

So the map gets a cap of its own, asking the question the editor was actually asking. Not "do these look alike" but "were these shot at the same spot on the same outing":

- **Places.** Candidates carrying a position are grouped by single linkage within `selection.place_radius_m` (150 m). Single linkage rather than a grid, because a walk along a beach is a chain of positions and a grid cell would split it at an arbitrary line. The radius is smaller than the 200 m spatial signal on purpose: that signal is a soft penalty and this is a hard cap.
- **Visits.** Inside a place, a gap longer than `selection.place_visit_gap_seconds` (two hours) starts a new visit. The same beach the next morning is a new outing and gets its own clips.
- **Position.** The telemetry fix nearest the window centre when the file has telemetry, otherwise the file's GPS tag. A drone's tag is written at takeoff and the shot can be three hundred metres away, which is two places at this radius.
- **The cap.** At most `selection.max_clips_per_place` (3) clips from one visit, as an eligibility filter like the cluster cap, lifted in the same last-resort pass as the minimum temporal gap when nothing else is eligible and slots remain. Three keeps a wide, a medium and a detail, which is how a montage covers a location.
- **No position, no cap.** Action cam files carry no GPS, so they belong to no place and are never held back by this. Absence of GPS is absence of evidence, not evidence of difference; embeddings cover those clips.

A candidate the cap held back stays a candidate with reason `place_cap` and records the clips that filled its visit, which the report shows by their edit order.

**Candidate share ceiling.** `selection.max_clips` is itself bounded to `selection.max_candidate_share` (half) of the eligible candidates, rounded up, unless `--max-clips` was passed. Forty slots for sixty candidates is not a selection but a rejection list: the diversity penalty can only reorder what it is forced to take anyway. Tying the slot count to the folder makes a small shoot produce a short edit without the user computing the number, while a large one still hits `max_clips` first. The ceiling is printed when it applies, because a user expecting forty clips has to be told why fewer came out.

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

Built in M4. Two levels:

- **Template generator**, always available and the only one that is. `soundtrack.genres` is an ordered table of rows, each with a `when` block (dominant tags, tags present, class shares, energy band, time of day, place region), a genre, two or three instruments with adjectives, a BPM range and mood words. The first row whose every condition holds wins, `soundtrack.default_profile` names the fallback, and the row that matched is recorded with the condition that made it match, so a surprising genre traces to one line of configuration. Scoring every row and taking the best was rejected for being unexplainable.
- **LLM refinement**, optional through OpenRouter, gated exactly like the vision calls. It receives the derived signals and the template prompt, never a frame and never a coordinate, and its answer is used only if it passes the same validator. A rejection keeps the template prompt and is recorded on the manifest.

Both paths go through formal validation before display: Description length, descriptor count, no sentences, no repeats, the instrumental marker last, one tag per line, one modifier per tag, no commas in brackets, valid section words, 3 to 6 tags per section, no vocal tags, no production adjectives as modifiers, every named instrument covered twice, `[end]` last. Every violation is returned with its line, not the first, because a GUI has to mark them all. A malformed prompt produces wrong music and the error is invisible by eye.

The app generates 3 to 5 variants differing in mood or instrumentation while sharing genre and BPM, and writes only the ones that validate.

**The proposed BPM is a fit, not a promise.** It is the integer in the row's range minimising the mean distance from each clip's assigned length to the nearest allowed beat count in `soundtrack.beat_multiples`. On the Sardinia edit that fit is poor by construction: the per-clip durations from M3 give 27 distinct lengths across 29 clips, no single BPM puts arbitrary lengths on a 2, 4 or 8 beat grid, and the best in range leaves a mean of 0.705 beats with only 4 clips within a tenth of a beat. Varied durations and a beat grid are two different goals, and reconciling them is what beat sync does by requantising against the measured track rather than hoping the lengths already land right.

**Place names** come from Nominatim reverse geocoding, one request per place centroid, cached forever under the cache directory by coordinates rounded to three decimals, spaced by `places.min_interval_s` and carrying a real user agent as its usage policy requires. `places.geocode = false` or an unreachable network keeps places numeric and drops the names from the prompt with one warning.

### 7.6 Beat sync

Built in M4.

- **Beat tracking.** The track is decoded by ffmpeg to mono at 22050 Hz, because Suno exports containers librosa has no business opening, and `librosa.beat.beat_track()` gives the beat positions. The user can override BPM with `--bpm`, because detection sometimes halves or doubles a steady tempo.
- **The BPM is the beat spacing, not the tracker's tempo scalar.** The two disagree: on a 120 BPM click librosa reports 117.5 while the beats it placed sit 0.5 s apart. The clip lengths are rounded onto the beat grid, so the number has to describe the grid. The spacing is a trimmed mean of the gaps, because librosa places beats on analysis frames 23 ms apart and the raw gaps therefore alternate around the truth, while a missed onset shows up as one doubled gap that the trim discards.
- **Durations on the beat.** Each clip is cut to a whole number of beats from `soundtrack.beat_multiples`, by default `{2, 4, 6, 8, 12, 16}`: half a bar to four bars at 4/4. At 120 BPM that is 1, 2, 3, 4, 6 and 8 s. The set stopped at 8 in the first version, which left a 6 s hero clip four beats from anything legal at any tempo in range. A clip whose segment is too short for the chosen multiple drops to the next smaller one. A clip too short for even the smallest takes its length from the span, and then carries no beat count and the reason `clamped`, because that length is the shot's and not the music's.
- **Window placement.** The final window is centered on the stored best window center, snapped to the analysis sampling grid so the cut lands on a frame that was actually measured, and shifted inside the segment bounds when it has to be. A window moved to a bound is snapped a second time, towards the inside of the span, because a trimmed bound is not a sampled instant unless the trim happens to be. A span with no sampled instant that holds the window keeps the bound instead and the clip records that the grid was out of reach: being inside the shot matters more than being on a measured frame. Export prefers these bounds over anything it would compute itself.
- **`beatmap.txt`** lists the beat times and then each clip with its cumulative start in the edit, which is enough to line clips up by hand in CapCut if anything drifts. Nothing in AutoCut reads it back.

**What it is worth.** Measured on the 29 clip Sardinia edit at 120 BPM, the distance of each clip's assigned length from a whole beat: a mean of 0.705 beats under the original multiples with 4 of 29 clips within a tenth of a beat, 0.419 and 6 of 29 after widening the set, and **zero across all 29** after quantising. Widening the set fixed one pathological clip; the requantisation is what puts the edit on the music. That is why varied durations and a beat grid are reconciled here rather than in section 7.4: they are different goals, and only one of them can be satisfied exactly.

**Contract with clip durations.** Beat sync does not derive durations from the score. Selection has already assigned each clip a duration and a reason (section 7.4), and beat sync rounds the assigned duration to the nearest allowed beat multiple. A clip whose reason is `hero` keeps the longer multiple when a rounding lands exactly between two, so the shots given room to breathe keep it. Alternation is likewise already applied, so beat sync inherits the rhythm rather than recreating it.

Result: clips in a row already fall on beats, CapCut auto beat sync has little or nothing to fix.

### 7.7 Export

ffmpeg cut, two modes:

- **Precise** (default): re-encode with `libx264 -crf 18`, 8-bit `yuv420p`, frame exact. Hardware encoders (`h264_videotoolbox`, `h264_vaapi`) are an opt-in for speed at the cost of cross-platform identical output.
- **Fast**: `-c copy` aligned to the nearest keyframe. For a first exploratory look only, documented as imprecise on durations.

Transformations:

- **Audio removal** (`-an`) by default, for every class. A default export is silent and the soundtrack carries the sound, which is what the first CapCut review asked for: two phone clips with ambience among thirty-eight silent ones is noise, not atmosphere. A class opts back in by setting `export.remove_audio.<class>` to false. Slow motion always removes it regardless: the video is stretched by an integer ratio and the audio is not, so keeping it would leave sound that stops partway through the clip.
- **Frame rate normalization.** `export.fps = "auto"` chooses, among the frame rates present in the selection, the one that the most selected clips reach by whole-number division, taking the lowest rate on a tie. It is recorded in the manifest export block, so deselecting one clip cannot move the target and invalidate every output already written. Clips converted from a non-multiple fps are flagged in the report. Explicit `--fps` overrides.

  The rule counts reach rather than clips, because the mode of the frame rates is the wrong answer on mixed footage. On the Sardinia set the selection is 24 clips at 50 fps, 14 at 25 and 2 at 30.033, so the mode is 50: analysis reads the Action 4 through its 25 fps `.LRF` proxy while export reads the 50 fps original, and the rate that dominates by count is one the analysis stage never saw. At a 50 fps target the Action 4 clips can never reach the two to one ratio slow motion needs, so that feature never fires, and every drone clip is upsampled for nothing. Counting reach gives 25, which 38 of the 40 clips arrive at by dropping whole frames, and with it 24 slow motion clips against 0 and 2 resampled against 16.

- **Resolution normalization.** Downscale to `export.max_resolution` (default 3840x2160), never upscale. The aspect of that maximum is the project aspect, which is what the vertical strategies pad or crop to.
- **One common frame** (`export.uniform_frame`, and always for a render). Mixed footage exports at mixed sizes, because a clip is only ever scaled down: the Sardinia edit came out as 9 drone clips at 3840x2160 beside 20 at 1920x1080. With the frame on, every clip is scaled to fit one frame and padded onto it centred. The frame's height is the smallest fitted height in the edit, so nothing is upscaled and the smallest clip is the quality ceiling; its width is the widest clip at that height, so one 4:3 clip is padded rather than putting bars down the side of every other clip. The frame is recorded on the manifest and only ever shrinks for a project, because rejecting the smallest clip must not re-encode all the others at a new size. Vertical strategies take the frame as their canvas, so a blur padded vertical clip comes out at exactly the frame.
- **Pixel format normalization** to 8-bit `yuv420p`. 10-bit passthrough is an option.
- **Slow motion.** Automatic when the source fps is at least twice the target and the class is `actioncam` (Action 4 at 50 fps to 25 fps target gives clean 2x). Off for other classes unless forced. Only whole ratios are used, so every output frame is a frame the camera took and nothing is interpolated.
- **Vertical clips.** Three strategies: exclude from selection (default), blur padded sides, center crop. Under `exclude` a vertical clip stays a candidate carrying the reason `vertical`, so the report shows it as held back by a policy rather than rejected on quality. Silent mixing of vertical and horizontal is the kind of error found only in CapCut.
- **LUT per class** through `lut3d`, with a class to `.cube` mapping in config. A hook only until log profiles are used.
- **Lens correction** for actioncam through `lenscorrection`, optional.

**Cutting exactly.** Precise mode seeks on the input, which ffmpeg does accurately, and trims with a frame count rather than `-t`. A window rarely starts on a source frame boundary, and `-t` then measures against the `fps` filter's own grid and can stop a frame early. Fast mode keeps `-t`, because a stream copy has no filter grid to align to and its bounds are approximate by definition.

**Resumable.** Every clip records a digest of everything its output depends on: the source, the window, the target frame rate and size, the mode, the codec and the filters. A clip whose file is on disk with a matching digest is skipped, so a re-export after a settings change re-encodes only what the change touched. Clips run in a process pool sized by `export.workers`, defaulting to half the analysis worker count (physical cores when neither is set), because libx264 is already threaded.

A clip whose encode fails for any reason, including a timeout, leaves no file at its output path, so a later run cannot mistake it for a finished clip. An exception while exporting one clip is recorded as that clip's failure and never stops the others.

**The final render (optional).** `autocut render <project>` joins the exported clips in edit order and mixes the synced track over them, writing `montage.mp4` beside `_selects/`. It exists because an edit whose clips, order and lengths are all decided needs nothing from an editor: the clips are already uniform, so the join is a stream copy plus one audio encode and costs seconds rather than a re-encode.

- Nothing is re-encoded except the track. The export it runs puts every clip on one common frame, so the clips match by construction; the uniformity check that follows is a safety net rather than a step the user is expected to satisfy. Fast mode is refused before anything is exported, because a stream copy carries each source as it is and no planner can make those uniform.
- The track is padded with silence when it is shorter than the edit, trimmed when it is longer, and faded out over `render.fade_out_seconds` (default 1.5). Without a track the render is silent, unless a class kept its own audio, in which case that audio is carried through.
- The render runs the export first when a clip has changed since the last one, because a render over stale clips would show an edit that no longer exists.
- It is keyed by the export fingerprints, the track and the fade, so a second run on an unchanged edit writes nothing. `render.enabled` makes an export run it as well, which is what the Export screen's toggle sets.
- Hard cuts only. No transitions, no titles, no color work, no speed ramps.

### 7.8 Output naming

CapCut imports in alphabetical order, so the filename carries chronology. The date is the local date of the clip, which is how the user reads it back against the days of a holiday:

```text
{index:03d}_{date}_{class}_{tag}_{duration}s.mp4

012_20260812_drone_sunset_4.0s.mp4
013_20260812_phone_family_2.0s.mp4
014_20260812_actioncam_snorkeling_2.0s.mp4
015_20260813_reflex_detail_4.0s.mp4
```

The tag is the segment's dominant tag, which is its most confident label from the primary group, or `clip` when no subject label beat its group's null prompt. A tag from another group never appears here: `aerial` says how a shot was taken and the class field already says it.

Output folder:

```text
output/
├── _selects/         # chosen clips, numbered
│   └── _stale/       # outputs of clips a later select dropped
├── _rejects/         # rejected clips, optional, reason in place of the tag
├── thumbs/           # per segment thumbnails and sprite strips
├── report.html       # visual review
├── manifest.json     # full analysis state, project file
├── suno-prompt.md    # prompt for the music generator
├── beatmap.txt       # beat positions, for reference in CapCut
└── montage.mp4       # the finished edit with the track, when a render was asked for
```

An output in `_selects/` that no longer belongs to a selected clip is moved to `_selects/_stale/`, never deleted. A mistaken `select` run should cost a re-encode, not the previous edit.

### 7.9 Review report

`report.html` is self contained and opens in a browser: grid with thumbnail, filename, duration, composite score, per metric scores, class, rejection reason. It lets the user delete wrong picks in two minutes before importing. The GUI replaces it in Phase 2, the CLI keeps producing it.

## 8. AI modules

Models are allowed and in some places clearly better than classic heuristics. Rules:

- **Graceful degradation.** The app works, with lower quality, without models, GPU or network.
- **Individually switchable** in config.
- **Cloud is optional and opt-out.** Cloud features turn on when `OPENROUTER_API_KEY` is present and turn off with `--no-cloud` or `providers.cloud = false`.

Modules in order of value over complexity:

1. **CLIP embeddings**, one per segment, local, computed from the 320 px thumbnail frame the analysis already cached, so no video is decoded a second time. `ViT-B-32/laion2b_s34b_b79k` through open_clip, on CUDA, MPS or CPU in that order. The vectors live in the file's cache entry beside the metric arrays together with the model identifier, so changing the model recomputes them and leaves the metrics alone. `autocut embed` fills a project that was analyzed without the extra, and `autocut analyze` calls it at the end when the extra is there. Without it analysis completes, records `embedding_model: none` and prints one line. Built in M3.
2. **Semantic similarity for deduplication.** The best similarity signal by far. The cosine between two normalized vectors is stretched from `similarity.semantic_floor`, 0.5 by default, up to 1 onto 0 to 1, because two unrelated holiday shots still score around 0.5 against each other. It replaces the perceptual hash for any pair where both candidates carry a vector rather than being averaged with it, so the mean holds one visual opinion and not two; a pair missing one vector falls back to the hash on its own. Built in M3.
3. **Semantic tagging.** Local zero-shot from the segment embedding against a configurable label set, or a cloud vision model. Feeds the filename tag, category balancing and the soundtrack prompt. Built in M3, and the shape of it came from measurement rather than from the obvious design.

   Labels live in **groups**, one softmax each: `subject` (beach, mountain, city, street, indoor, food, people), `view` (aerial, underwater) and `light` (sunset). Labels that can be true at the same time must not compete, and one softmax over all ten made them: a drone shot over a beach scored `beach` at a cosine of 0.2886 against `aerial` at 0.2052, so `beach` took all 27 drone segments and `aerial` appeared on none.

   Each group carries a **null prompt** that joins its softmax, is never emitted, and has to be beaten before a label is. A group whose probabilities sum to one over its labels alone always emits something; and a probability threshold alone means different things in a group of two rows and a group of eight, which put `sunset` on all 77 segments of a set with no sunset in it.

   The **logit scale** is `tags.logit_scale`, default 10. CLIP's own 100 belongs to its contrastive loss: at 100 the distribution is one-hot, every segment took a tag, and no threshold rejected anything.

   Only the **primary group** names a file. A view or a lighting tag says how a shot was taken, which the source class already says. On the Sardinia set 55 of 77 segments get a subject, 22 fall back to `clip`, every one of the 20 `aerial` tags is on a drone clip, and `autocut tag` runs in 5 s.

4. **Captions**, cloud vision model only. One lowercase sentence of at most twenty words per segment, stored on `Segment.caption`, shown on the report card and feeding the M4 soundtrack prompt. Asked for in the same request as the tags and the aesthetic, because three fields cost one call. Built in M3.
5. **Aesthetic scoring.** A rating from 1 to 10 stored on `Metrics.aesthetic` scaled to 0 to 1 so it rank normalizes beside the other metrics. It enters the composite score only when `weights.aesthetic` is above zero, which is not the default; a class where no segment has one leaves the metric out entirely. Two sources fill it, and `Metrics.aesthetic_source` says which. With `providers.aesthetic` on and the `ai` extra installed, the local stage applies LAION's aesthetic-predictor V1 linear head, bundled with the package, to CLIP embeddings of each segment's cached thumbnail. The head was trained on OpenAI CLIP vectors, so those come from a second tower, `ViT-B-32-quickgelu/openai`, and never from the laion2b embeddings used for deduplication and tags (ADR 15). The cloud model's judgment replaces a local value and is never overwritten by one; a value with no source, from a manifest written before this, counts as cloud. `autocut describe` scores the project again after writing descriptions, and the local stage does the same when `weights.aesthetic` is above zero and a value changed, because scoring otherwise happens during analysis and would be stale. Turning `providers.aesthetic` off removes the local values. The aesthetic is judged per segment, so it moves a segment's score and never the window chosen inside it. Cloud path built in M3, local path in M4b.
6. **Face detection**, YuNet through `cv2.FaceDetectorYN`, model bundled (ADR 14). Family scenes have value no sharpness metric sees. With `providers.faces` on, analysis counts the faces on every sampled frame (score at least `analysis.face_score_threshold`, height at least `analysis.face_min_height_share` of the frame) and stores the counts as the `faces` cache array with the model id in `face_model`. A segment's `Metrics.faces` is the `analysis.face_count_percentile` percentile of the counts inside it. It is a weighted metric, `weights.faces`, default 0, and shapes the best window. It also protects deduplication: with `similarity.face_guard` on, two segments whose counts are both known and differ have similarity 0, so similar frames with different people are not duplicates. Counts only, never identity. The family profile turns detection on and sets the weight. Built in M4b.
7. **LLM prompt refinement**, through OpenRouter, output always validated.
8. **Narrative ordering by LLM**, low priority. Group by place from GPS instead of pure chronology.

## 9. Data model

`manifest.json` is the single source of truth and the project file. For each analyzed segment: source path, proxy path if any, class, in and out points, best window center, all raw metrics, composite score, outcome (selected or rejected) with reason, tags, caption, embedding reference, exported path. Opening a manifest in the GUI restores the full review state. The schema is versioned. A manifest from a newer schema is refused rather than loaded and rewritten, and an older one is brought up to date one version at a time by a migration step on load.

**Analysis cache** is global, in the platform cache directory (`~/.cache/autocut/` on Linux, `~/Library/Caches/autocut/` on macOS). The key is size, mtime and a hash of the first and last 1 MB, without the path, so a file read over a share or copied with its mtime preserved keeps its entry; a copy that resets the mtime is analyzed again. Per source file, one `.npz` with metric arrays, embeddings and the per-shot `aesthetic` ratings, plus a JSON with probe and telemetry and the `embedding_model` and `aesthetic_model` identifiers. The arrays include `faces`, the per-frame face count, and the JSON records `face_model`, only when face detection ran. Re-running on the same footage with different weights is instantaneous, in any project. See ADR 6.

## 10. CLI

```bash
# what this machine can do
autocut doctor
autocut key set                      # store an OpenRouter key in the keychain

# first pass
autocut analyze    ./footage --out ./edit-sardinia
autocut embed      ./edit-sardinia   # only when analyze ran without the ai extra; also scores aesthetics when providers.aesthetic is on
autocut tag        ./edit-sardinia   # after editing the label set in autocut.toml
autocut describe   ./edit-sardinia   # cloud tags, captions and aesthetics, needs a key
autocut select     ./edit-sardinia --max-clips 40 --duration 3.0 --diversity 0.6
autocut soundtrack ./edit-sardinia --variants 3   # --bpm and --genre override the fit
autocut report     ./edit-sardinia

# generate the track externally, then second pass
autocut sync       ./edit-sardinia --audio track.mp3   # --bpm overrides the measurement
autocut export     ./edit-sardinia --no-audio
```

Commands are separate and re-runnable, reading and writing the same manifest. Tuning means running `select` twenty times over one `analyze`.

`autocut sync` without `--bpm` measures the real BPM and compares it to the one proposed by `soundtrack`, warning on mismatch. `--bpm` wins when given.

`autocut run` chains the first pass. Configuration comes from `autocut.toml` with command line overrides. All CLI output is in English.

An unknown configuration key, a value outside its allowed range, an explicit `--config` path that does not exist, and an unreadable or invalid manifest are each reported in one line and exit status 1, never a traceback.

## 11. GUI

Five screens with back and forward navigation. All strings in English. Started in M5, built on PySide6 as a consumer of the core: every stage the window runs is the same function the CLI calls, and nothing in `autocut/core` knows the window exists.

**Shape.** One `ProjectState` per open project owns the manifest and the configuration, exposes a Qt signal for every change, and is the only object that writes `manifest.json`, on a debounced timer. Core stages run one at a time in a `CoreWorker` on a `QThread`, with the progress callback bound to a signal and cancellation through a flag that callback reads. Screens are thin: they bind to state signals and call state methods. See ADR 9.

**Navigation.** A screen is reachable when the project has what it needs: Analysis once a project is open, Review once there are segments, Soundtrack and Export once something is selected. One function of the manifest decides all of it, so the rule is testable without building a window. The navigation is a slim rail of icons and labels down the left, ending in a block naming this machine's ffmpeg version, the embedding backend and whether cloud is on; over every screen sits a bar with the project name, its file and candidate counts, the counters of the edit and the current screen's own primary actions, which the screen hands the bar rather than the bar knowing about screens.

**Look.** The window brings its own design rather than borrowing the desktop's, so it renders the same on Linux and macOS: the Fusion style on every platform, a palette and a stylesheet generated from one token module in `autocut/gui/theme`, and Space Grotesk, IBM Plex Mono and a subset of the Lucide icons shipped as package data and registered at startup. Every colour, size and radius is a token; a test walks the GUI package and fails on a hex string or a hand built `QColor` outside the theme package, so a change of design is a change of one file. The type scale is 11, 12, 13, 16, 18 and 20 px on an 8 px spacing grid, and every number a reviewer compares (scores, durations, timecodes, BPM, counters, badges) is set in the mono face so a column of them does not jitter. `gui.theme` takes `dark`, `light` or `system` and defaults to dark, applied at the next start; `system` reads the desktop palette once at startup. Bundled fonts that fail to register fall back to the platform families with one logged warning, never a refusal to open the window. The bundled assets are redistributed under the SIL Open Font License 1.1 and the ISC licence, listed in `THIRD_PARTY_LICENSES.md`. See ADR 10, and `docs/design/` for the mockup the design was approved from.

1. **Project and sources.** Built in M5. Drag and drop source folders, or browse; a dropped file counts as the folder holding it. Clip counts per folder from the extension rule alone, so the number shown before a run is the number the run will consider. Output folder, and it says so when that folder already holds a project, offering to continue rather than start again. Profile (drone, family, mixed) applied as a diff the user sees first. Recent projects in the platform config directory, and the `doctor` report inline, so a missing ffmpeg is seen before a run rather than during one.
2. **Analysis.** Built in M5. Stage steps, progress with the current file, elapsed and an estimate that stays blank until a second file has finished, because one file pays for every warm up there is. Cancel, which stops at the next progress report and keeps what was reached. Resume, which is a normal run made cheap by the analysis cache; the button says Resume when a probed file has neither a segment nor an error, which is what a cancel leaves behind. Runs in a worker, the UI never blocks.
3. **Review.** Built in M5. The central screen, and the reason the GUI exists: no scoring gets every pick right, and the fix has to take a click. A grid of rounded cards by chronology or score, each with a picture area tinted by source class until its thumbnail loads, a badge saying what the clip is (`IN n` in the accent, `KEPT n` in amber, `OUT` muted, `REJECTED` in red, and `hero` under it for a clip given room to breathe), its length and beat count top right, the class and score on one line, the tags as chips, and last where and when it was shot or, when it is out, the clip it lost to and how close it came; a human decision outranks the machine's, so a keep is amber and a reject is red whatever the selection made of them; filters as a row of chips that turn the accent colour when they are filtering something; hover scrubbing that walks the segment's sprite strip under the pointer; keep and reject by click or keyboard (K, R, space, U for undo) with an undo stack; a preview that plays the clip in a `QVideoWidget` from its in point and pauses at its out point, with the sound muted until asked for and the sprite strip taking its place when the platform has no decoder, and in and out points snapped to the sampling grid; filters by class, tag, place, outcome, rejection reason and score range, with a toggle for the clips the rules threw out; scoring weight sliders that re-score from the cache and re-sort, and a diversity slider that re-selects, both on the screen rather than in a dialog; a similar-groups view of clusters and place visits as stacks where one click swaps the pick for the clip behind it, summarised in one line at the foot of the right panel; the counters of the edit in the window's top bar rather than on the screen, project wide whatever the filters show, because they are about the project and every screen wants to read them; Export report, so the report the CLI wrote reflects the review; and Play all, which renders the whole edit as one low resolution file and plays it with the montage strip under the grid, one rounded block per clip with played blocks in the muted accent and the one playing in the accent, so the sequence can be judged the way CapCut will play it. The right panel holds, top to bottom, the file with its time of day and length, the preview, the in and out points as one mono line, Play clip and Automatic window, the diversity slider with `best only` and `most varied` under its ends, the weights as a table with a reset, and the similar groups line. While the montage plays, the grid follows it, clicking a boundary jumps to that clip, and K, R, space and U apply to the clip on screen rather than to the grid cursor, so a clip can be rejected as it plays. A decision marks the montage stale and says so without interrupting playback.

**User decisions are core, not GUI.** `Segment.user_decision` (`keep` or `reject`) and `user_start_s` and `user_end_s` live in the manifest, so `autocut select`, `autocut export` and `autocut sync` honour them and the report shows them. A keep is selected before class shares and the greedy loop and is never dropped for a cap, which the header says when the pins alone outgrow `max_clips`; a reject is ineligible and does not count towards the candidate ceiling; hand set bounds replace the searched window and the assigned duration, take the reason `user`, and are what beat sync quantises inside and export cuts. Clearing a decision returns the clip to the automatic rules on the next selection. This is what makes the promise of the screen true: nothing automatic undoes what a person said.

**Live sliders, measured.** Re-selection reads only the cached arrays, so it runs on the UI thread behind a `gui.slider_debounce_ms` debounce (250 ms), and a project past `gui.reselect_worker_threshold` candidates (300) goes to the worker instead. Measured on the 60 candidate Sardinia project: a re-selection is about 485 ms, so a slider answers well inside a second but not inside the quarter second the design hoped for; most of what is left is reading 72 cache entries again on every run. Sprite strips are skipped when selection reads an entry, which took that number down from 1.5 s.

4. **Soundtrack.** Built in M5. The two pass music loop on one screen, because it is one loop. On the left the prompt: Title, Description and Structure each with a Copy button, a variant switcher, the matched genre row with the reason it matched, an editable BPM that regenerates, and two mood controls, calmer to more energetic and cinematic to intimate, which pick between the mood words the matched row already carries and never change the genre. Each position is absolute rather than relative: every move is applied to the variants as generated, so "as matched" goes back and asking twice does not compound. The blocks are editable and every keystroke runs the validator, which marks each violated rule on its own line with the rule in a tooltip; a valid edit can be kept as the chosen variant with source `user`, is written first in `suno-prompt.md`, and survives a regeneration; an invalid block asks before it is copied, because the rules are Suno's and they change. On the right the track: the waveform as a min and max envelope with the detected beats as ticks, the measured BPM, the comparison with the drift and half or double messages, a BPM override that the half and double cases pre-fill, and a preview of what the tempo would do to the edit, from the same quantisation code that will do it, before Apply runs beat sync through the worker. The manifest records which track and tempo the final bounds were computed from, because a measurement is not a sync: loading a track writes what it measures while the clips stay cut to whatever the last sync used, and without that record a project synced yesterday looked synced to today's track. After a sync, Play with track renders the montage with the track muxed and plays it in the same player, because a beat grid that is subtly wrong looks right and sounds wrong, and inferring that from numbers is not the same as hearing it.
5. **Export.** Built in M5. Every export option in one place: mode, codec, quality, target fps, maximum resolution, vertical strategy and the rejects folder, plus a per class grid for keeping the audio, slow motion, lens correction and a LUT file. The screen asks whether to keep the audio where the configuration asks whether to remove it, because that is the question a person has. Options are written to `autocut.toml` beside the manifest as they change, so the command line sees the same project. A dry run says how many clips, how long, at what frame rate, how many will be slowed or resampled and whether they are on the beat grid. The run goes through the worker with a bar and the current clip; the summary gives the clips written, skipped and failed, the length, the folder size and the errors by clip; stale files from an earlier selection are counted and their deletion offered, never automatic, and only for the files directly under `_selects/_stale/`.

**The montage preview.** `autocut/core/montage.py` renders one small file per selected clip and joins them: one ffmpeg pass per clip at `gui.montage_height` (360 px) with a fast preset, reading proxies where they exist, then a concat by stream copy that muxes the track. Not one filter graph over every input, because twenty-nine 4K decoders at once is gigabytes of memory and no progress to report. Windows come from `plan_export`, so the montage cuts what the export will cut. The video's own length always wins: the audio is padded and the output trimmed to the montage, since `-shortest` cut a 77 s edit down to a 20 s track when it was tried.

Each montage is written to `preview/montage-<fingerprint>.mp4`. Rebuilding over one path corrupts whatever is playing it: the render leaves the file it replaces alone and hands it back, and the screen deletes it only once its player has been pointed at the new one.

Both the whole montage and each part carry a fingerprint of what they were made from, so pressing Play all on an untouched edit renders nothing and one changed clip re-renders only the parts whose windows moved. `preview/montage.json` records each clip's measured span, which is what the timeline draws and what maps a playback position to a card: the durations ffmpeg produced, not the ones the edit asked for. The montage runs about one frame per clip longer than the export, because each part is a whole number of frames.

**The mood scales.** `soundtrack.calm_to_energetic` and `soundtrack.intimate_to_cinematic` order the mood words the rows use, and the two controls pick the word furthest along whichever scale they move. A word missing from a scale counts as neutral rather than guessed at: the scales rank the words this project ships, not every word in English, and a test asserts every shipped row's words appear in both.

Cross cutting: no long operation on the UI thread, state saved continuously to the manifest, API keys stored in the OS keychain through `keyring` and never written to `autocut.toml`. Network calls, audio analysis and folder walks never run on the UI thread, and closing the window during a stage cancels it and waits for the current file without freezing the window, saving only once the worker has stopped. The settings dialog writes the fields it edits into `autocut.toml` next to the manifest, merged over what is already there, so the window and the command line share one project.

**Testing.** Qt runs on the offscreen platform, under the `gui` marker, in a `dev-gui` Docker target and its own CI job. Offscreen tests prove a window builds and behaves and prove nothing about whether it is readable, so a marked test grabs one PNG per screen, in both the dark and the light token set, into `$AUTOCUT_GUI_SHOTS` for a reviewer. Those images are never committed and are only ever of the synthetic fixtures (ADR 8).

## 12. Performance

Target: 100 GB of 4K analyzed in under 30 minutes on the M4 MacBook.

Levers, by impact:

- **Proxies** (`.lrv`, `.lrf`) when present. Free 5x.
- **Sampled decoding**, 2 fps at 320 px. Note that on HEVC with long GOPs, seeking to 2 fps still decodes most frames, so hardware decode matters more than the sample rate.
- **Hardware decode**, chosen once per run rather than per file and verified by decoding one frame of the first file, with a single demotion to software for the whole run if that fails. `analysis.hwaccel` accepts `auto`, `off`, `vaapi` and `videotoolbox`. `auto` selects videotoolbox on macOS and software elsewhere; it never selects CUDA, which is what ffmpeg's own `-hwaccel auto` picked on the AMD development host before failing on every file.

  Hardware decode is a lever only where it measures as one. On the AMD iGPU it is not: sampling one 4K clip at 2 fps measured 3.9 s in software against 9.0 s through VAAPI, and 5.7 s with a full GPU filter chain. At this sample rate most of the work is skipping frames rather than decoding them, and every decoded surface still crosses back to system memory, so VAAPI has to be asked for by name. The macOS figure is the one that matters for the 100 GB target and is still to be measured on the M4.

- **Parallel files**, sized on physical cores: analysis uses a `ProcessPoolExecutor`, because decoding, shot detection and the metrics are CPU bound; ingest and export use a `ThreadPoolExecutor`, because their workers mostly wait on a subprocess (ffprobe, a subtitle extract, ffmpeg) and gain nothing from a separate interpreter that would only re-import numpy, cv2 and pydantic per worker.
- **Global cache.**
- **One probe per file** (issue #82). Analysis takes dimensions, rotation, duration, frame rate and streams from the probe ingest already ran, through `probe_from_source`, instead of running `ffprobe` on the file a second time.
- **One copy of the sampled frames** (issue #82). `read_frames` decodes straight into one growing array instead of a list of byte chunks later joined and reshaped, and motion and content differences are computed between consecutive frames rather than by stacking every frame as float64 at once. Together these hold one copy of a file's sampled frames in memory instead of about seventeen, bounding a long 4K file's analysis worker to a small constant over the size of its sampled frames rather than tens of gigabytes.
- **A selection entry cache** (issue #82). Re-selection reads every candidate's analysis cache entry and recomputes its visual hashes on every run, which is what the review sliders trigger on every move. `read_entry_cached` keeps up to `cache.memory_entries` recently read entries in memory, read-only, keyed on each file's `stat` so a rewritten or deleted entry is read again; `CacheEntry.derived` memoises the perceptual hash and color histogram per entry so repeated re-selection over an unchanged project computes them once.

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

- **M0, foundation** (done 2026-09-03). This spec, ADRs, repository skeleton, config and manifest schemas, Docker dev setup, CI, synthetic fixture generator.
- **M1, ingest and analysis** (done 2026-09-03). Scan, probe, proxy discovery, telemetry adapters (DJI embedded subtitle first), classification, classic metrics, manifest, global cache. Output: `report.html` only. Verifies scoring on real footage before building on it.
- **M2, selection and export** (done 2026-09-03, plus per-clip durations and the place cap on 2026-09-03). Best window, rejection rules, deduplication with classic signals, cutting, normalization, naming. The tool is useful from here.
- **M3, embeddings and diversity** (done 2026-09-04; the live cloud validation run is pending the user's key). CLIP or SigLIP, semantic similarity, greedy selection with penalty, tagging (local and cloud), captions.
- **M4, soundtrack.** Complete. Template prompt, validation, variants, optional LLM refinement, place names. Beat tracking, beat durations, BPM check, `beatmap.txt`.
- **M4b, remaining AI.** Done 2026-09-29: face detection (ADR 14) and the local aesthetic predictor (ADR 15).
- **M5, GUI.** Complete. Five screens on the existing core, plus user decisions in the manifest and the mood controls in the prompt.
- **M6, packaging.** macOS `.dmg` on CI, first run model download.

Stopping after M2 to use the tool on real footage before continuing is expected. Scoring weights are tuned on real material and every later milestone builds on that tuning.

## 16. Open items

- **Fujifilm footage** is needed to validate the `reflex` class. Until then it is best effort.
- **Genre defaults** in `soundtrack.genres` are placeholders until the user tunes them.
- **Action 4 gyro** in `djmd` is unparsed. Shake detection relies on image metrics. Revisit only if results are poor.
- **Insta360 `.insv`** is accepted by extension but untested. Requiring an MP4 export from Insta360 Studio is acceptable.
- **Distant faces** are not counted. At the default `analysis.sample_long_side` of 320 px, a child a few metres from an action camera has a face of 5 to 8 px, below YuNet's floor of about 10 px (real-footage check of issue #95). Close faces count correctly. Revisit with a larger sample size for detection only if family footage needs it.

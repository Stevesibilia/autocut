# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Python floor raised to 3.12, every dependency floor raised to the newest release at least 5 days old, and a generated `constraints.txt` now pins every transitive version for the venv, Docker images and CI (ADR 11).
- `scenedetect` moves from a core dependency to the optional `scenedetect` extra: the default install carries a single `cv2` distribution, `opencv-python-headless` (ADR 11).
- Analysis reuses the probe ingest already ran instead of a second `ffprobe`; ingest and export run their subprocess-bound workers on threads instead of a process per file; sampled frames decode into one growing array and motion and content differences are computed pairwise, holding one copy of a file's sampled frames instead of about seventeen; and selection keeps recently read cache entries in memory, read-only, with their visual hashes memoised, sized by the new `cache.memory_entries` (issue #82).
- External tool calls now go through one `run_tool` runner in `autocut/core/proc.py`, and every timeout is a field in the new `[timeouts]` table of `autocut.toml`, alongside newly configurable `analysis.high_fps_threshold`, `analysis.fallback_fps`, `similarity.histogram_bins`, `similarity.hash_share` and `export.workers`. The CLI and GUI now run analysis through one shared `autocut/core/pipeline.py`: a cancelled `autocut analyze` stops before embed, tag and describe the way the GUI already did, and the GUI now records the cloud model, request count and cost the way the CLI already did. `autocut/cli/main.py` is split into `output.py`, `common.py` and one module per command group under `autocut/cli/commands/`, with the same commands and the same `--help`. The default tag, genre and mood tables move out of `autocut/core/config.py` into plain data in `autocut/core/config_defaults.py` (issue #81).

### Removed

- Python 3.11 support.

### Fixed

- A clip that made ffmpeg write a lot of decode errors could hang its worker forever, because the sampler read stderr only after stdout ended. ffmpeg's stderr is now drained on a background thread while frames are read, so any amount of error output cannot block decoding.
- An unexpected exception from one file's worker aborted the whole analysis, ingest or export run and discarded every result already finished. Each worker's result is now collected on its own, so a failing file never stops the others.
- Ctrl-C during analysis lost the files already finished. It now stops the run like a cancellation: finished files keep their segments, the manifest is saved, and the command line exits with status 130.
- Ingest and export now check that `ffprobe` and `ffmpeg` are on PATH before starting any worker, and fail once with a clear error naming the missing tool instead of reporting it per file.
- A truncated or otherwise corrupt cache entry raised instead of being recomputed. Reading any unreadable entry, one whose metadata names another file, or one whose arrays and metadata were written by different runs, now misses and the file is recomputed; entries written before this change keep loading. `prune` also removes orphaned metadata and leftover temporary files.
- `autocut.toml` now rejects an unknown key and an out-of-range value at any level. An explicit `--config` path that does not exist, an unreadable or invalid configuration file, and an unreadable or invalid manifest each fail with one line and exit status 1 instead of a traceback.
- A failed or timed-out export could leave a partial clip at the output path, where the next run would mistake it for a finished one. The clip is now removed on any encode failure.
- Loading a manifest that needs a migration now copies the original file to `manifest.v<N>.json.bak` before the first migration step runs.
- The window no longer freezes while the Soundtrack screen refines the prompt with a hosted model or measures a track: the request and the beat tracking run on the worker thread, and the screen updates when they finish. Generating without the cloud stays immediate. A genre or BPM change made while a generation runs is applied once afterwards instead of reporting that a stage is still running.
- The export summary uses a folder size measured by the export worker, so finishing an export no longer walks the selects folder on the UI thread.
- Closing the window during a stage no longer blocks for up to 70 seconds or saves the manifest while the worker is still writing it. The stage is cancelled, the window stays open with a message, and it closes by itself once the current file is done. `ProjectState.close_project` now returns whether it closed, and gives up without saving when the stage does not stop within `gui.close_wait_ms` (5000).
- Finished worker threads are deleted instead of staying parented to the project state for the rest of the session.

## [0.5.0] - 2026-09-28

- `autocut gui`, a PySide6 window over the same core the CLI uses: one `ProjectState` per project owning the manifest and configuration with a debounced autosave, a `CoreWorker` thread that runs any core stage with progress and cooperative cancellation, and a five screen window whose navigation unlocks a screen when the project has what it needs (ADR 9).
- The Project screen: drag and drop or browse for source folders with clip counts, an output folder that says when it already holds a project, the drone, family and mixed profiles applied as a diff the user sees first, a recent projects list, and the `doctor` report inline.
- The Analysis screen: stage steps, progress with the current file and an estimate, cancel that keeps what it reached, and resume made cheap by the analysis cache.
- The settings dialog: cloud toggle, API key through the OS keychain, hardware decoder, worker count, cache folder and size, the four scoring weights, maximum clips and diversity, written into `autocut.toml` beside the manifest so the CLI sees the same values.
- The `gui` extra pinned to PySide6 6.11.2, a `dev-gui` extra for `pytest-qt`, a `gui` Docker target running Qt offscreen, `make docker-test-gui` and a `gui` CI job. A `gui` pytest marker skips these tests when PySide6 is absent.

- User decisions in the core: a segment can be kept or rejected by hand, and can carry hand set in and out points. A keep is selected before the class shares and the greedy loop and is never dropped for a cap; a reject is ineligible and does not count towards the candidate ceiling; hand set bounds replace the searched window and the assigned duration with the reason `user`, are what beat sync quantises inside and what export cuts. `autocut select`, `autocut export` and `autocut sync` honour them and the report shows them.
- The Review screen: a card grid sortable by chronology or score, hover scrubbing over the sprite strip, keep and reject by click or keyboard with an undo stack, a preview with in and out points snapped to the sampling grid, filters by class, tag, place, outcome, rejection reason and score range, a toggle for the clips the rules rejected, weight and diversity sliders that re-score and re-select live, a similar-groups view of clusters and visits where one click swaps the pick, a header counting the edit project wide, and Export report.
- `thumbs.sprite_for_segment` builds one segment's strip from the cache without decoding video, so a project whose `thumbs/` was cleaned scrubs again on the first hover.
- `score.rescore` recomputes every segment's score from the metrics in the manifest, which is what a weight slider needs and what the CLI can now reuse.
- `gui.slider_debounce_ms` (250), `gui.reselect_worker_threshold` (300) and `gui.grid_thumbnail_px` (196).

- The Soundtrack screen: the three prompt blocks with copy buttons and live validation marking each violated rule on its line, a variant switcher, an editable BPM and genre row that regenerate, two mood controls that pick between the matched row's own words, a hand edited prompt kept as the chosen variant, the track's waveform with its beats, the tempo comparison with a pre-filled override for the half and double cases, a preview of what a tempo would do to the edit, and Apply sync through the worker.
- The Export screen: every export option including a per class grid for audio, slow motion, lens correction and LUT files, written to `autocut.toml` as they change, a dry run of what the export would do, the run itself with progress and cancel, a summary with the folder size and the failures by clip, and the offer to delete the stale files an earlier selection left behind.
- `soundtrack.prompt.apply_mood` moves a prompt along two mood axes inside the matched row, with `soundtrack.calm_to_energetic` and `soundtrack.intimate_to_cinematic` ordering the words the shipped rows use.
- `soundtrack.build.store_user_variant` keeps a hand edited prompt when it validates, writes it first in `suno-prompt.md`, and keeps it there through a regeneration.
- `beatsync.envelope` reduces a decoded track to min and max pairs for the waveform, cached beside the manifest by the audio file's size and modification time.
- `quantize_durations(..., dry_run=True)` reports what a tempo would do without touching a segment, so the preview and the run cannot disagree.

- The montage preview: `autocut/core/montage.py` renders the selected clips in edit order into one 360 px file with the track muxed, keyed by a fingerprint of the edit so an untouched selection renders nothing and one changed clip re-renders only what moved, with `preview/montage.json` recording each clip's measured span.
- Play all on the Review screen: the whole edit in one player with a timeline marked at every cut, the grid following the clip on screen, a click on a boundary jumping to that clip, and K, R, space and U applying to the clip playing so it can be rejected as it plays.
- Play with track on the Soundtrack screen after Apply sync, which is how the beat grid is heard rather than inferred.
- `gui.montage_height`, `gui.montage_preset` and `gui.montage_crf`; a `preview` block on the manifest.
- The export screen offers to delete a montage preview built from an edit that no longer exists, alongside the stale clip files.

- The final render: `autocut render <project> [--track] [--out]` joins the exported clips in edit order by stream copy and mixes the synced track over them, writing `montage.mp4` beside `_selects/`. It exports first when a clip has changed, refuses clips that do not share codec, size, pixel format, frame rate and audio layout rather than writing a file that falls apart, pads a short track with silence, trims a long one and fades it out, and writes nothing when the edit and the track have not changed.
- `autocut/core/avmux.py` holds the concat list, the audio filter, the joined command and the ffmpeg runner that the montage preview and the final render share.
- "Also render the montage with the track" and its fade length on the Export screen, written to `autocut.toml`: an export with the toggle on finishes with the render, and the summary names the file with its duration, size and track and offers to open it.
- The report header shows the rendered file with its duration, size and clip count when one exists.
- `render.enabled` (false), `render.fade_out_seconds` (1.5), `render.filename` (`montage.mp4`) and `render.audio_bitrate` (192k); a `render` block on the manifest.

- The common export frame: `export.uniform_frame` and `autocut export --uniform-frame` scale and pad every selected clip onto one frame, the smallest fitted height in the edit and the widest clip at that height, so nothing is upscaled and one 4:3 clip does not narrow the frame for everything else. A render turns it on for the export it runs, so mixed 4K and 1080p footage renders with the default settings. The frame is recorded on the manifest and never grows for a project, vertical strategies take it as their canvas, and the report header and the Export screen name it.
- `autocut render` refuses `export.mode = "fast"` before exporting anything, since stream copied clips carry their sources' parameters and cannot be made uniform.

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

- Soundtrack prompt: `autocut soundtrack` derives the edit's signals, matches a genre row, fits a BPM to the clip lengths, writes 3 to 5 validated Suno prompts into `suno-prompt.md`, and records all of it on the manifest. `autocut run` calls it after select.
- Genre table of twelve ordered rows seeded from the user's own genres, each with a `when` block, instruments carrying adjectives, a BPM range and mood words. First match wins and the matched row is recorded with the condition that made it match.
- Prompt validator enforcing every Description and Structure rule from SPEC.md section 7.5, returning every violation with its line rather than the first.
- Place names from Nominatim reverse geocoding, one request per place centroid, cached forever, spaced and identified as the usage policy requires. `places.geocode = false` or no network keeps places numeric.
- Optional prompt refinement through the OpenRouter text model, gated like the vision calls, sending only derived signals and the template prompt. Its answer is used only if it passes the validator; a rejection keeps the template and is recorded.
- The review report header shows the genre, the matched row and why, the proposed BPM, the mean distance from a whole beat, and a link to the prompt file. Places are listed by name and region when geocoding found them.

- Beat sync: `autocut sync --audio <track>` decodes the track through ffmpeg, measures its beat grid, rounds every selected clip to a whole number of beats, stores final bounds centred on the best window and snapped to the sampling grid, and writes `beatmap.txt`. Export cuts to those bounds. A span with no sampled instant that holds the window keeps the shot's own bound and records that the grid was out of reach; a span too short for even the smallest multiple gives the clip its length, no beat count and the reason `clamped`. Measured on the Sardinia edit, all 29 clips land exactly on the beat where 4 of 29 did before.
- The BPM comparison names a drifted track and spots the half and double tempo cases, offering the `--bpm` flag that fixes them. Sync runs without the soundtrack step and says the comparison was skipped.
- The review report shows each clip's beat count beside its duration and a header panel with the measured BPM, the comparison and a link to the beat map.

- `read_entry` no longer decompresses the sprite strips unless asked, and selection asks it not to. The strips are most of the bytes in an entry and selection never looks at them: on the Sardinia project this took a re-selection, which is what every slider move costs, from 1.5 s to 485 ms.
- The review grid keeps the cursor on the clip it was on across the model reset that every re-selection causes, so working down the grid with the keyboard is possible.

- The Soundtrack screen labels both mood axes by their ends, "Calm to energetic" and "Intimate to cinematic". Moving one while a hand edited prompt is the chosen variant leaves that prompt untouched and says so.
- The review grid's cards carry a coloured border and a corner badge for kept, rejected and selected, rather than only a number in a row of numbers.
- The groups view labels each clip with its file name and time instead of the segment's content hash, and shows at most four alternatives with a count of the rest.
- `ProjectState` records a stage's result before it emits `stage_finished`, so a screen reading it in that handler gets this run's result and not the previous one.
- An empty string in a per class LUT table reads back as no LUT, which is how the GUI writes "nothing set" into a TOML table that has no null and needs every key.

### Changed

- The review report lists selected segments first, with their edit order, best window bounds, visual cluster and the near duplicate a candidate lost to.
- Selection holds back display-vertical candidates when `export.vertical_strategy` is `exclude`, marking them with the reason `vertical` while they stay candidates, so the report shows them as excluded by policy rather than rejected on quality.
- The review report links each selected card to its exported file and marks fast cuts and clips resampled from another frame rate.
- Selected cards show the clip's target duration, the rule that settled it and whether its window was snapped to a motion boundary.
- `export.remove_audio` defaults to true for every class: a default export is silent and the soundtrack carries the sound. Set a class to false in `autocut.toml` to keep its ambience.
- The review report shows each segment's place, offers a filter by place, lists the places with their visits and clip counts, and names the clips that filled a visit on a card the place cap held back.
- `soundtrack.beat_multiples` defaults to 2, 4, 6, 8, 12 and 16 beats, half a bar to four bars at 4/4. Stopping at 8 left a 6 s hero clip four beats from anything legal at any tempo in range.
- The prompt's Structure varies its mood word per section from the genre row's alternates. It repeated one word in every section, wasting tags that are meant to cover different dimensions.
- `cache.models_dir` is separate from `cache.dir`, so a project with its own analysis cache no longer downloads its own copy of the model weights. Weights belong to the machine and default to the platform cache directory.
- `soundtrack.genres` is an ordered list of rows rather than a dictionary of profiles. The old shape had no way to say when a row applies.
- The dominant tag prefers the first cloud tag when a segment has one, since a model that looked at the picture is more specific than a zero-shot label set. A local re-run replaces only local tags and leaves cloud tags alone.
- `Segment.tags` is a list of `Tag` records rather than of strings. A manifest written before the change opens unchanged: a string list upgrades to local tags with confidence 1.0.
- Tests that are not marked `ai` no longer touch the real vision model. With the extra installed, every CLI test running `analyze` was downloading the model into its own temporary cache.
- A cache entry whose stored embedding model differs from the configured one reads back with no embeddings and with its metric arrays intact, so changing the model costs one forward pass per shot rather than a re-analysis.

### Fixed

- A track loaded after an earlier sync counted as synced, because every clip still carried beats from that sync, so the montage went out with the new music over the old cuts and every number on screen agreed with it. The manifest now records the track and tempo the final bounds were computed from, and Play with track follows that.
- Rebuilding the montage wrote over the file the player still had open, which produced `Invalid NAL unit size` errors and a black picture. Each montage is written to a file named after its fingerprint, the player is unloaded before a rebuild and pointed at the new file after it, and the old file is deleted only then.
- Loading a track, and moving the BPM override, refresh Play with track: it stayed enabled from a previous sync.
- The line under the Review header showed the montage's duration next to the header's edit total. The montage's length is in the player's transport row alone.

- An export skipped a clip whose position in the edit had changed, leaving another clip's footage under its name. The output name carries the index, and the fingerprint covers only what the bytes look like, so rejecting a clip could hand its neighbour a file it did not write. A clip is skipped only when the file recorded for it is the one its plan would write.

- A failed stage left the Review, Soundtrack and Export screens disabled: it emits neither `stage_finished` nor `stage_cancelled`, and nothing else re-enabled them until the next stage ran.

- The Review screen's Play showed nothing: the player had no video output, so Qt decoded every frame, discarded it and reported no error. The panel now holds a `QVideoWidget` the player draws into, with a muted `QAudioOutput` and a sound toggle, seeks to the in point only once the media reaches `LoadedMedia` because a position set before that is dropped, pauses at the out point, and falls back to the sprite strip only when the platform really has no video for the file. A test counts frames in a `QVideoSink` and asserts the pause, and it fails against the old code.
- The preview says when a file ends before its out point instead of leaving "playing from the in point" under a still picture. Found on a 1.9 s clip from the real footage.

- GUI tests waited for a signal a worker emits from inside its own run and then ended, so a `QThread` could be collected while its thread was still running, which makes Qt abort the process. About one run in fifteen locally, with the suite still reporting every test passed.

- `scripts/make_fixtures.py` returns immediately when the synthetic set is already complete, and otherwise builds it in a temporary directory and moves each file into place, so several test runs starting at once no longer regenerate the same files on top of each other. Pass `--force` to rebuild a complete set.

- The window brings its own design instead of the desktop's, so it renders the same on Linux and macOS (ADR 10): the Fusion style everywhere, a palette and a stylesheet generated from one token module, and Space Grotesk, IBM Plex Mono and twenty Lucide icons shipped as package data. Every colour, size and radius is a token, and a test fails on a colour literal anywhere else in `autocut/gui`.
- `gui.theme` (`dark`, `light` or `system`, default `dark`), editable in the settings dialog and applied at the next start. **BREAKING** for the look on macOS, which no longer uses the native style.
- The navigation becomes a rail of icons ending in a block naming this machine's ffmpeg version, embedding backend and cloud state, and a top bar carries the project name, its counts, the counters of the edit and the current screen's primary actions.
- The Review screen matches the approved mockup: rounded cards with pill badges, per class placeholder tints, tag chips, and, for a clip that is out, the clip it lost to and how close it came; filters as chips; the montage as a strip of blocks under the grid with a mono counter and the key hints; a right panel with the preview, the bounds, diversity, the weights and a similar groups line.
- Analysis shows a card per stage with a mono counter, Export puts cut, codec and vertical clips on chips and the final render on its own card, and the screens that can be empty say so in one sentence with one action.
- The screenshot test writes every screen in both token sets into `$AUTOCUT_GUI_SHOTS`.
- `THIRD_PARTY_LICENSES.md`, listing the bundled fonts and icons with their licences.

- The window fits a laptop again. Several rows were laid out so that their full width was their minimum, and Qt will not shrink a window below its layout's minimum, so on a 1440x900 MacBook the window opened larger than the screen and could not be resized. The filter chips and the decision buttons now wrap, the Soundtrack, Analysis and Project screens scroll, the top bar elides the project name and moves actions it cannot fit into an overflow menu, and the Review right panel collapses from a control in the top bar, collapsed by default under `gui.panel_collapse_width`. Measured offscreen: the window's minimum size hint went from 1958x1060 to 949x650.
- `gui.min_window_width` (1100), `gui.min_window_height` (680) and `gui.panel_collapse_width` (1280). The window sets the minimum from them and opens at the smaller of 1440x900 and the available screen.
- Play did nothing: the Play buttons connected `clicked(bool)` straight to a slot whose first argument is the video output, so Qt received `False` and raised. The stale files button carried the same defect, and there it deleted the files without ever showing its confirmation dialog.

- Icons were a corner of themselves on a Retina screen. `QSvgRenderer.render(painter)` fills the painter's device rectangle in device pixels, so at ratio 2 the glyph was drawn at twice the size it was asked for and only its top left quarter reached the pixmap.
- The Review right panel keeps its content inside its 336 px: the file name and the range label elide with the whole text on a tooltip, the preview placeholder wraps instead of demanding 480 px of its own, and the weight value columns take their width from the font. Panel content went from 520 px to 278 px.
- Stop is enabled whenever a player exists rather than only while it is playing, so the pause at the out point no longer leaves a paused clip and a dead button, and stopping returns the preview to the strip at the in point.
- `autocut gui --diagnose` prints the screens with their device pixel ratios, the fonts registered and in use, the resolved theme and the window's minimum size hint and opening size, then exits.

- The Review screen's centre column and right panel sit in a splitter the user drags, so the preview is as large as they make the panel. The panel keeps a 280 px floor, neither column collapses by dragging, and hiding the panel keeps the width it had.
- The navigation rail collapses to a 56 px strip of icons with the labels on tooltips.
- The rail state, the split position and the panel visibility are remembered per machine in `layout.json` in the configuration directory, never in the manifest.
- The preview sits in a 16:9 stage that takes its height from the panel's width, so playing a 4K clip no longer stretches the panel into a black column and pushes every control under it off the screen.
- Playing on macOS: the video page is shown before the source is set, because the widget is a native layer that never paints a frame decoded before it existed, and Stop pauses, stops, detaches the video output and hides the widget, since reordering Qt's stack leaves a native layer where it is.
- `gui.panel_min_width` (280) and `gui.rail_collapsed_width` (56).
- `autocut gui --verbose` logs the playback and layout steps to the terminal. Nothing in the project configured logging before, so every `info` and `debug` line written for a bug report went nowhere.

- Play all had no way back: it replaced the Review grid with the montage player and nothing brought the tiles back. The player carries a Back to clips button, Escape does the same while the montage has focus, and the top bar action reads Back to clips while the montage is showing. All three return to the grid with the clip that was playing selected and shown in the preview.
- Opening a manifest written by a newer AutoCut silently dropped its unknown fields, and the GUI's autosave then wrote the stripped file back over the original. Loading now refuses a newer `schema_version` with a message naming both versions, leaves the file untouched, and reports it as one line and exit status 1 on the command line or a warning dialog in the window.

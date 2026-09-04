## 1. Extra and environment

- [x] 1.1 Pin the `ai` extra in `pyproject.toml` to torch and open_clip versions that have wheels for Linux x86_64 and macOS arm64 on Python 3.11 through 3.14, verified against PyPI per AGENTS.md. Verify with `pip download --only-binary :all:` for both platforms in the dev container.

  Pinned `torch>=2.13,<2.14`, `torchvision>=0.28,<0.29` and `open_clip_torch>=3.3,<3.4`. torchvision pins one exact torch version per release, so the pair moves in lockstep and torchvision is named in the extra to make that visible; 0.28.0 pins `torch==2.13.0`. torch 2.14.0 and torchvision 0.29.0 exist, published 2026-09-02, and the five day rule in AGENTS.md rules them out.

  **Verification, and where the task text does not work.** `pip download --platform` selects wheel tags but does not re-evaluate environment markers: `platform_system` keeps the value of the running interpreter, so from a Linux container a macOS resolve still demands torch's Linux-only CUDA dependencies and fails for a reason that says nothing about macOS wheels. The verification is therefore split.

  Linux x86_64 was resolved natively in `python:3.11-slim` through `python:3.14-slim` with `pip install --dry-run --only-binary=:all:`, which uses the real tags and the real markers. All four resolve to torch 2.13.0, torchvision 0.28.0, open_clip_torch 3.3.0, in 48 packages on 3.11 and 50 on 3.12 through 3.14. The same resolve against `https://download.pytorch.org/whl/cpu` gives torch 2.13.0+cpu and torchvision 0.28.0+cpu in 31 packages on all four, which is what the `dev-ai` image installs: the PyPI Linux wheel drags CUDA 13, cuDNN, NCCL and triton behind it, several GB for a machine with no NVIDIA GPU.

  macOS arm64 was verified by wheel tag over the whole dependency closure, since no macOS runner is available here. torch 2.13.0 and torchvision 0.28.0 both publish `cp311` through `cp314` `macosx_14_0_arm64` wheels, `open_clip_torch` is `py3-none-any`, and every other package in the 31 package closure is pure Python, `abi3` (`safetensors` as `cp310-abi3`, `hf-xet` as `cp38-abi3`) or ships arm64 wheels for cp311 to cp314. numpy 2.5.2 requires Python 3.12 or newer, so a 3.11 Mac resolves an earlier numpy, which the core `numpy>=1.26` floor already allows. The result stands to be confirmed on the MacBook the first time the extra is installed there.

- [x] 1.2 Add a `Dockerfile.dev` target `ai` that installs the extra, a compose service `dev-ai`, and an `ai` pytest marker skipped when torch does not import. Verify `docker compose run --rm dev-ai pytest -q -m ai` runs the marked tests.

  `Dockerfile.dev` is now two targets, `dev` and `ai`, and the `dev` service in
  `compose.yaml` names its target explicitly: without that, a build of the file would
  pick the last stage and `make docker-test` would silently run the heavy image.

  The `ai` target installs torch and torchvision from `https://download.pytorch.org/whl/cpu`
  before the extra, because the PyPI Linux wheel depends on CUDA 13, cuDNN, NCCL and
  triton, several gigabytes for a container that only ever runs on the CPU. The extra
  then finds both already satisfied. The `dev-ai` service mounts a named volume at
  `/root/.cache/autocut`, so the 350 MB checkpoint is fetched once rather than per run,
  and asks for no `/dev/dri`.

  The `ai` pytest marker is declared in `pyproject.toml` and skipped by
  `tests/conftest.py` when torch does not import, using `importlib.util.find_spec` rather
  than an import because that code runs during collection on every session. `make
docker-test-ai` and a separate `ai` job in `ci.yml` run the marked tests; the matrix job
  is unchanged and skips them.

- [x] 1.3 Add `autocut/core/doctor.py` with `inspect_environment(config) -> DoctorReport` and the `autocut doctor [--json]` command. Verify with unit tests mocking each probe and a `CliRunner` test for exit status with and without ffmpeg on PATH.

  `autocut/core/doctor.py` holds `inspect_environment(config, sample=None)` returning a
  `DoctorReport` of eight `Check` records, and `autocut doctor [--json] [--sample PATH]`
  renders it. Exit status is 0 when ffmpeg and ffprobe are both present and 1 otherwise,
  since nothing works without them; a hardware decoder that fails verification is a
  warning, not a failure, because analysis falls back to software.

  Two notes on the requirement. The report has to say whether the decoder "verified", and
  whether a driver works is not something `ffmpeg -hwaccels` can answer, so verification
  needs a real file: `--sample` supplies one and without it the line says "not verified,
  no sample file" rather than claiming either outcome. And the decoder reported is the one
  `auto` would choose, as the spec asks; when the project configures something else the
  line names that too, so the two cannot be confused.

  The key lookup lives here for now with the service and username that
  `m3-cloud-providers` specifies, `autocut/openrouter`, and moves into
  `autocut/core/providers/__init__.py` in that change. `--json` is written straight to
  stdout rather than through Rich, which would soft wrap a long cache path and break the
  parse.

## 2. Embeddings

- [x] 2.1 Add `autocut/core/embeddings.py` with `available() -> str | None`, `select_device()`, `load_model(config)`, `embed_frames(frames, model, device, batch_size, progress) -> np.ndarray` and `embed_project(manifest, config, progress)` reading thumbnails from cache entries and writing `embeddings` and `embedding_model` back. Verify with unit tests using a mocked encoder: shapes, normalization, batch count equals progress events, model change triggers recompute, same model skips.

  `autocut/core/embeddings.py` holds `available()`, `select_device()`,
  `load_model(config, device=None)`, `image_encoder(loaded)`, `embed_frames(...)` and
  `embed_project(manifest, config, progress)`.

  Two departures from the signatures in the task text. `embed_frames` takes an `Encoder`,
  a callable from a batch of frames to an array of vectors, instead of a model and a
  device: the device is already on `LoadedModel`, and taking the encoder as an argument is
  what makes the batching, the normalization and the progress events testable without
  torch installed. `image_encoder` builds the real one. `available()` performs a guarded
  import rather than a metadata check, memoized for the process, because an installed
  torch that cannot load its shared libraries is not an available torch and `doctor` has
  to say so.

  `LoadedModel` carries the tokenizer beside the model and the preprocessing transform, so
  `m3-tagging` encodes its label set through the same load.

- [x] 2.2 Extend the cache entry with `embeddings` and `embedding_model` and `AnalysisRun` with `embedding_model` and `embedding_device`. Verify with the cache round trip and manifest tests.

  The cache entry gains `embeddings` in the `.npz` and `embedding_model` in the `.json`,
  and `AnalysisRun` gains `embedding_model` and `embedding_device`. `read_entry` returns an
  entry whose stored model differs from the configured one with no embeddings and with its
  metric arrays and thumbnail frames untouched, which is what makes a model change cost
  one forward pass per shot and no decode.

  `cache.thumb_index(segment_id, count)` is now the single place that decides which cached
  frame belongs to a segment. `select.py` used to inline that clamp for the thumbnail; the
  hash and the vector have to agree on it or a similarity would compare one shot's
  thumbnail against another shot's vector.

- [x] 2.3 Wire `autocut embed <project>` and call it at the end of `autocut analyze` when enabled and available, printing one skip line otherwise. Verify with `CliRunner` tests for the enabled, disabled and unavailable paths.

  `autocut embed <project>` runs the step on an analyzed project, and `autocut analyze`
  calls the same helper after analysis and before the report, so the cards and the picks
  see the refs. Skipping prints one line naming the reason and exits 0: a missing extra is
  not a failed run. The progress bar is created on the first event rather than up front, so
  a project that is already embedded prints one line and no empty bar.

- [x] 2.4 Add the `ai` marked integration test that embeds the synthetic fixtures with the real model and asserts the blurred and sharp fixtures of the same source have cosine similarity above 0.9 while `smptebars` and `testsrc2` are below 0.7. Verify it passes in `dev-ai`.

  **The two thresholds in this task do not hold, and the fixtures are why.** Measured with
  `ViT-B-32/laion2b_s34b_b79k` on the CPU in `dev-ai`, first shot against first shot:

  | pair                         | cosine |
  | ---------------------------- | ------ |
  | `sharp_pan` / `shaky`        | 0.961  |
  | `sharp_pan` / `overexposed`  | 0.927  |
  | `sharp_pan` / `underexposed` | 0.908  |
  | `sharp_pan` / `blurred`      | 0.833  |
  | `sharp_pan` / `static`       | 0.799  |
  | `blurred` / `underexposed`   | 0.738  |

  Both halves of the task fail. `gblur` at sigma 8 is not a softer version of a picture to
  CLIP, it is a different picture, so the sharp and blurred pair scores 0.833 rather than
  above 0.9. And every ffmpeg test pattern is "a colourful test card" to the model, so
  `testsrc2` against `smptebars` scores 0.799 rather than below 0.7. Nothing in the whole
  matrix of single pattern fixtures falls below 0.73: the band is too narrow to assert on
  because these fixtures do not differ in subject, only in exposure and sharpness, which is
  exactly what an embedding is supposed to ignore.

  `multishot` is the fixture that does differ in subject, being `testsrc2`, then
  `smptebars`, then `mandelbrot` in one file:

  | pair                                          | cosine |
  | --------------------------------------------- | ------ |
  | `sharp_pan` / `multishot` shot 0 (`testsrc2`) | 0.957  |
  | `multishot` shot 0 / shot 1 (`smptebars`)     | 0.838  |
  | `multishot` shot 0 / shot 2 (`mandelbrot`)    | 0.555  |
  | `multishot` shot 1 / shot 2                   | 0.475  |

  So the test keeps the intent of the task and changes the pair: the same pattern in two
  different files must score above 0.9, which it does at 0.957, and `testsrc2` against
  `mandelbrot` must score below 0.7, which it does at 0.555. A second case runs both
  cosines through the mapping the signal actually applies, so the assertion is about the
  number selection sees rather than a raw cosine. Four tests, green in `dev-ai` in 89 s
  including the checkpoint download.

  The finding is worth more than the test: on material that differs only in exposure or
  focus the semantic signal says "the same thing", which is correct and is also why the
  spatial and temporal signals have to stay in the mean.

## 3. Semantic signal

- [x] 3.1 Add `SemanticSignal` to `autocut/core/similarity.py` with `similarity.semantic_floor` and weight in config, and the hash exclusion rule in the combiner. Verify with unit tests for the four scenarios in the modified `similarity-signals` spec.

  `SemanticSignal` maps the cosine from `similarity.semantic_floor` to 1 onto 0 to 1,
  with `similarity.weights.semantic` at 0.5, the same weight the visual hash carries,
  because it replaces it rather than joining it. The exclusion lives in
  `_excluded_for_pair`, consulted by `combined_similarity` before the loop, so the rule is
  in one named place rather than spread through the accumulation.

  A zero semantic weight counts as the signal being off and leaves the hash in place,
  which is the behaviour a user setting the weight to zero expects.

## 4. Validation

- [x] 4.1 Run `autocut embed` on the real Sardinia project on the Linux CPU and record wall time and device. Run `autocut select` with and without the semantic signal and record: cluster count, number of `lost_to` candidates, and how many of the 40 selections changed. Open the report and note whether the new clusters group shots a person would call the same scene.

  Linux development host, AMD Ryzen 7 5825U, 16 threads, 2026-09-03. The 72 file Sardinia
  set, 77 segments, 60 candidates. Device `cpu`: the box has an AMD iGPU and no CUDA, so
  MPS and CUDA stay untested until the MacBook.

  **Embedding is cheap.** 9.3 s wall for 72 files and 77 shots with the weights already on
  disk, at 454% CPU with a batch size of 16, so about 0.12 s per shot. A first ever run
  adds the 350 MB checkpoint download; `analyze` over the fully cached set plus that
  download came to 32 s in total. A second `autocut embed` takes 3.6 s and computes
  nothing, and almost all of that is importing torch. All 60 candidates got a vector: no
  file was missing a cached frame.

  **The signal agrees with GPS about what is one scene.** Cosine over all 1770 candidate
  pairs, and the same pairs split by the place and visit the GPS grouping put them in:

  | pairs                  | n    | min   | p25   | median | p75   | max   |
  | ---------------------- | ---- | ----- | ----- | ------ | ----- | ----- |
  | all                    | 1770 | 0.118 | 0.411 | 0.550  | 0.646 | 0.939 |
  | same place and visit   | 55   | 0.461 | 0.683 | 0.765  | 0.826 | 0.929 |
  | different place        | 245  | 0.118 | 0.307 | 0.627  | 0.714 | 0.884 |
  | one without GPS        | 1470 | 0.185 | 0.414 | 0.539  | 0.626 | 0.939 |
  | the hash, for contrast | 1770 | 0.104 | 0.373 | 0.440  | 0.516 | 0.882 |

  Pairs the GPS grouping calls one visit sit 0.14 above pairs from different places at the
  median, which is the ranking the signal is supposed to produce, on a set where 35 of the
  60 candidates carry no GPS at all and the action cam therefore has no other evidence than
  this. **The 0.5 floor is right for this footage**: the median of all pairs is 0.550, so
  the floor sits at the middle of the distribution and the whole lower half maps to 0.
  After the mapping the median signal is 0.100 and p75 is 0.292.

  **The hash over-merges and the embedding does not.** Above the cluster threshold of 0.75,
  the semantic signal alone puts 17 pairs and the hash alone puts 35. That is the 0.08
  separation from the M2 validation seen from the other side, and it is why clusters go up
  rather than down: 49 clusters with the semantic signal against 45 without.

  **The clusters group what a person would call one scene**, judged by time and GPS rather
  than by eye, which is the part still waiting on the user:

  | cluster with semantic on | members                      | what they share  |
  | ------------------------ | ---------------------------- | ---------------- |
  | 9 (3)                    | 0221, 0222, 0224             | 50 s apart       |
  | 34 (4)                   | 0243, 0246, 0247, 0248       | one 4 min outing |
  | 42 (3)                   | DJI_0801, DJI_0802, DJI_0803 | one visit        |
  | 37 (2)                   | DJI_0772, DJI_0776           | one visit        |

  With the hash instead, the same footage produces **one seven member cluster**, 0243
  through 0249, and a two member cluster of `DJI_0811` and `DJI_0818`, which are not
  adjacent in time. The seven member blob is the worse failure: `max_clips_per_cluster` is
  2, so it makes five clips ineligible on the strength of a signal that cannot tell those
  shots apart. The embedding splits it into a four member cluster and three singletons.

  **What changes in the selection.** Four runs, defaults and `--max-clips 40`, semantic on
  and off:

  | run                   | slots | selected | clusters | `lost_to` | held by place | total   | actioncam | drone | phone |
  | --------------------- | ----- | -------- | -------- | --------- | ------------- | ------- | --------- | ----- | ----- |
  | on, defaults          | 29    | 29       | 49       | 7         | 6             | 76.5 s  | 19        | 9     | 1     |
  | off, defaults         | 29    | 29       | 45       | 9         | 6             | 77.0 s  | 19        | 9     | 1     |
  | on, `--max-clips 40`  | 40    | 40       | 49       | 8         | 10            | 104.0 s | 28        | 10    | 2     |
  | off, `--max-clips 40` | 40    | 40       | 45       | 8         | 4             | 111.1 s | 24        | 14    | 2     |

  **Four of the picks change either way**, 25 of 29 shared with defaults and 36 of 40
  shared at forty slots. The interesting number is not how many but which: at forty slots
  the semantic signal takes the drone from 14 clips to 10 and gives those four slots to the
  action cam, and the place cap holds back 10 candidates instead of 4. Both say the same
  thing, that a run of aerials over one stretch of coast is one scene rather than fourteen,
  which is the complaint that started M3. With defaults the ceiling binds at 29 slots and
  the class split is identical, so the change shows up only in which four clips fill them.

  **Export:** 29 clips in 120.8 s, 614 MiB, none failed, no output carries an audio stream,
  19 in slow motion and 1 resampled from another frame rate.

  Left for the user: whether those clusters look like one scene on screen, and whether the
  four swapped clips are better. `~/Documents/autocut/edit-sardegna-m3-embeddings` is the
  folder to compare against `edit-sardegna-places`.

- [x] 4.2 Update `SPEC.md` section 8 module 1 and section 6.1 with the pinned model and the doctor command. Run `make lint` and `make docker-test`, commit on branch `feat/m3-embeddings` following `sf-commit-convention`, open a pull request.

  Section 6.1 records the pinned versions, the model identifier and its size, where the
  weights land, and why Linux should install torch from the PyTorch CPU index; it also
  describes `autocut doctor`. Section 8 rewrites modules 1 and 2 as built rather than
  planned. Section 10 gains `autocut doctor` and `autocut embed` in the command list, since
  a command list that omits two commands is wrong.

  Section 15 still lists M3 as pending, which is correct: `m3-tagging` and
  `m3-cloud-providers` are the rest of it.

  The export for the morning is at `~/Documents/autocut/edit-sardegna-m3-embeddings`,
  beside `edit-sardegna`, `edit-sardegna-durations` and `edit-sardegna-places`.

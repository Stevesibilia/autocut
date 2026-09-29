## Context

Read on `main` at `f7959a0` (0.6.0):

- `embed_project` (`autocut/core/embeddings.py:290-354`) embeds `entry.thumb_frames`, one 320 px RGB frame per detected shot. It stores the L2-normalised vectors as `entry.embeddings` together with `entry.embedding_model`, and sets `segment.embedding_ref = f"{file_id}:{index}"` with `index = thumb_index(segment_id, rows)` (`cache.py:84-100`). The model loads lazily and only when some file is not fresh.
- `load_model(config, device)` (`embeddings.py:184-221`) reads the model name from `config.providers.embedding_model` and loads it with `open_clip.create_model_and_transforms(arch, pretrained=..., cache_dir=models_dir(config))`. On MPS it runs in half precision. `image_encoder(loaded)` (`:224-241`) returns unnormalised float32 vectors. `normalize` is at `:281-287`. `weights_present(config)` (`:158-177`) and `doctor._weights_check` (`doctor.py:150-160`) only know the configured embedding model. The `ai` extra is guarded through `available()`, `_torch()` and `_open_clip()` (`:81-115`).
- LAION's head `sa_0_4_vit_b_32_linear.pth` (`https://github.com/LAION-AI/aesthetic-predictor`, MIT) is an `nn.Linear(512, 1)` state dict: 3,047 bytes, SHA-256 `c7b14cead230694acc7b9447974d3cad78003c72da032e402a303b6c2429e85f`. Its notebook embeds with `open_clip.create_model_and_transforms(..., pretrained='openai')` and L2-normalises before the head. The output is a rating on a 1 to 10 scale. The project's embeddings come from `laion2b_s34b_b79k`, a different vector space, so the head cannot be applied to them.
- Cloud aesthetic: `describe.apply_description` (`describe.py:181-202`) sets `metrics.aesthetic = description.aesthetic / AESTHETIC_RANGE[1]` with `AESTHETIC_RANGE = (1, 10)` (`:39`). `describe._rescore` (`:395-419`) returns early when `weights.aesthetic <= 0`, and otherwise does what `score.rescore(manifest, weights)` (`score.py:68-89`) does. `Metrics` (`manifest.py:180-191`) uses the default `extra="ignore"` (see the manifest-version-guard design, decision 3), so an added optional field needs no schema bump.
- The crash: `window.frame_scores` (`window.py:74-78`) does `arrays.get(METRIC_ARRAYS[metric])` for every `SCORED_METRICS` entry with a positive weight. `METRIC_ARRAYS` (`:25-31`) has no `aesthetic`, so `ScoringWeights(aesthetic=1.0)` raises `KeyError` in every selection (`select.py:243-258`). The GUI slider can already trigger it.
- The pipeline (`pipeline.py:80-119`) runs `analyze_files`, which scores, then `run_embed`, `tag_project` and `run_describe`. `AnalysisOutcome` (`:27-36`) carries each result. The CLI prints them (`cli/commands/analyze.py:108-110`, `cli/output.py:24`), and so does the GUI (`gui/screens/analysis.py:280-305`). `autocut embed` is `cli/commands/enrich.py:66-76`.
- `providers.aesthetic: bool = False` (`config.py:605`) exists and nothing reads it.

## Decisions

**1. Bundled head.** Download `https://github.com/LAION-AI/aesthetic-predictor/raw/main/sa_0_4_vit_b_32_linear.pth`. Check it is 3,047 bytes with the SHA-256 above. Commit it as `autocut/core/models/laion_aesthetic_vit_b_32_linear.pth`, with the upstream `LICENSE` beside it as `autocut/core/models/LAION-AESTHETIC-LICENSE.txt`. Add `"autocut/core/models/*"` to `artifacts` in `[tool.hatch.build.targets.wheel]`, unless it is already there. In `THIRD_PARTY_LICENSES.md`, add a row to a `## Models` section (create the section if it does not exist yet: #95 adds one in parallel), and update the opening paragraph so it no longer says only fonts and icons are redistributed. Ship the file as published, not converted, so its provenance can be checked by hash.

**2. The second tower.** In `autocut/core/aesthetic.py`:

```python
AESTHETIC_TOWER = "ViT-B-32-quickgelu/openai"
HEAD_FILENAME = "laion_aesthetic_vit_b_32_linear.pth"
AESTHETIC_MODEL_ID = f"{AESTHETIC_TOWER}+laion-sa-0.4-linear"
```

`AESTHETIC_TOWER` is a constant, not configuration. The head is only valid for that tower, so letting the tower vary would silently produce noise. OpenAI's CLIP uses QuickGELU. In open_clip 3.3 the `-quickgelu` architecture with `pretrained="openai"` is the entry that builds the right activation. In the `ai` container, confirm with `open_clip.list_pretrained()` that `("ViT-B-32-quickgelu", "openai")` is listed, and that loading it logs no QuickGELU mismatch warning. If it is not listed, stop and report what is.

Generalise the loader without changing behaviour for the embedding model: `load_model(config, device=None, name=None)` and `weights_present(config, name=None)`. `name=None` means `config.providers.embedding_model`, as today. The tower lands in the same `models_dir(config)`.

**3. The head in numpy.** `load_head() -> tuple[np.ndarray, float]` loads the bundled file with `_torch().load(path, map_location="cpu", weights_only=True)`. It checks the state dict holds exactly `weight` with shape `(1, 512)` and `bias` with shape `(1,)`, and returns `weight[0]` as float32 plus `float(bias[0])`. Resolve the path with `importlib.resources.files("autocut.core").joinpath("models", HEAD_FILENAME)` and `as_file`. `rate(vectors: np.ndarray, weight: np.ndarray, bias: float) -> np.ndarray` returns `normalize(vectors) @ weight + bias`. It is pure numpy and tested without torch.

**4. The stage.** `score_aesthetics(manifest, config, progress=null_progress) -> AestheticResult` in `aesthetic.py`. `AestheticResult` is a dataclass with `model: str | None`, `device: str | None`, `segments: int` (local values written), `kept_cloud: int`, `files_computed: int`, `files_from_cache: int`, `skipped_reason: str | None` and `warnings: list[str]`. The stage:

- Returns `skipped_reason="aesthetic scoring is disabled by configuration"` when `providers.aesthetic` is off. First it clears every `Metrics.aesthetic` whose `aesthetic_source == "local"` (set both to `None`), so that turning the feature off leaves no stale local values. The cleared values are not counted in the result. If any were cleared and `weights.aesthetic > 0`, rescore as below.
- Returns `skipped_reason=available()` when the `ai` extra is missing. Existing values are left alone.
- For each file with segments, `read_entry`. If `entry.aesthetic_model == AESTHETIC_MODEL_ID` and `entry.aesthetic.shape[0] == entry.thumb_frames.shape[0]`, the ratings are fresh. Otherwise it loads the tower once, lazily, as in `embed_project`. It encodes `thumb_frames` with `image_encoder` in `providers.embedding_batch_size` batches, with progress events like `embed_frames`, and rates them. It stores the per-shot ratings as `entry.aesthetic` (float32, clipped to `AESTHETIC_RANGE`), sets `entry.aesthetic_model`, and calls `write_entry`.
- For each segment, `index = thumb_index(segment.id, rows)`, the same mapping as `embedding_ref`. If the segment is a cloud value, count it in `kept_cloud` and leave it. A cloud value is `aesthetic_source == "cloud"`, or `aesthetic is not None and aesthetic_source is None`, which is a manifest written before this change, when only the cloud could set it. Otherwise set `metrics.aesthetic = rating / AESTHETIC_RANGE[1]` and `aesthetic_source = "local"`.
- Afterwards, if `config.weights.aesthetic > 0` and any value changed, call `score.rescore(manifest, config.weights)`.

Move `AESTHETIC_RANGE` from `describe.py` to `aesthetic.py` and import it in `describe.py`, so both scales are defined in one place. This keeps `aesthetic.py` free of `describe`'s imports.
Rejected: applying the head to the laion2b vectors, which is the wrong space. Replacing the embedding model with the OpenAI one: that would change dedup and tags, which were tuned on laion2b. A second pass over sampled frames instead of the per-shot thumbnails: the thumbnails are what `embed` and `describe` already judge, and they are free.

**5. Cache.** `CacheEntry` gains `aesthetic: np.ndarray | None = None` and `aesthetic_model: str | None = None`. `write_entry` stores `aesthetic` in the npz under that name when it is not `None`, and `aesthetic_model` in the JSON, exactly like `embeddings` and `embedding_model`. `read_entry` loads them the same way. Do not add `aesthetic` to `ARRAY_NAMES`: that list is per-frame arrays, and these values are per shot. `read_entry` applies no staleness rule; the stage does.

**6. Manifest and describe.** Add `aesthetic_source: Literal["local", "cloud"] | None = None` to `Metrics`, right after `aesthetic`. `apply_description` sets `aesthetic_source = "cloud"` wherever it sets `aesthetic`. Replace the body of `describe._rescore` with the weight guard followed by `score.rescore(manifest, config.weights)`. The class lookup is the same. Keep `_rescore` as a name, because its tests call it. No `MANIFEST_SCHEMA_VERSION` bump: the field is optional, and an older build ignores it.

**7. Pipeline, CLI, GUI, doctor.**

- `pipeline.run_aesthetic(manifest, config, progress) -> AestheticResult` wraps `score_aesthetics`. `analyze_project` calls it right after `run_embed` and stores it in the new `AnalysisOutcome.aesthetic: AestheticResult | None = None`. Describe runs later and overrides with cloud values; it rescores on its own.
- `autocut embed` runs `run_aesthetic` after embedding, because both are the local-model step. `analyze` does the same through the pipeline. Both print `output.print_aesthetic(result)`:
  - on skip: `Aesthetic scoring skipped: <reason>`, but only when `providers.aesthetic` is on, so a default run prints nothing new;
  - otherwise: `Scored [bold]N[/bold] segments for aesthetics with <tower> on <device> (F files computed, C from cache, K kept from cloud)`;
  - then the warnings in yellow, like `print_embed`.
- `gui/screens/analysis.py` `describe_outcome`: one line with the same numbers after the embeddings line, under the same "only when enabled" rule.
- `doctor`: when `providers.aesthetic` is on, add a check named `aesthetic_weights`, built like `_weights_check`, on `weights_present(config, AESTHETIC_TOWER)`, with the same wording. It is informational (`ok=False` only means a download is pending), exactly like `model_weights`. When the feature is off, no check is added.

**8. The window fix.** In `window.frame_scores`, look the array name up with `METRIC_ARRAYS.get(metric)` and `continue` when there is none. Add a comment: `aesthetic` is judged per segment, so it moves the segment score, not the choice of window inside a segment. `build_class_norms` needs no change. #95 adds a `faces` entry to `METRIC_ARRAYS` in parallel. Leave that map as it is.

**9. Configuration.** Give `providers.aesthetic` a description: it scores every segment locally with LAION's aesthetic predictor on a second CLIP tower (OpenAI ViT-B/32, about 350 MB, downloaded once), needs the `ai` extra, and a cloud judgment replaces it. Add `aesthetic = false` under `[providers]` in `autocut.example.toml` with a one-line comment. Regenerate `tests/fixtures/autocut_config_snapshot.json` if the description is part of the snapshot. Defaults stay: `providers.aesthetic = false`, `weights.aesthetic = 0`.

**10. ADR and docs.**

- `docs/adr/0015-local-aesthetic-predictor.md` in the house format (`# 15. Local aesthetic predictor on a second CLIP tower`, Date 2026-09-28, Status Accepted). It records the head, the second tower and why, the bundling, and "cloud wins". It amends SPEC §8 item 5 and ADR 4's list of what cloud serves.
- `SPEC.md`:
  - §5.1: the aesthetic score is local by default when enabled.
  - §6.1: say "the bundled LAION aesthetic head and a second, OpenAI ViT-B/32 tower for it", and correct the stale "torch 2.13, torchvision 0.28" to 2.14 and 0.29.
  - §8 item 5: rewrite with the local path, `aesthetic_source` and the rescore.
  - §9: the per-shot `aesthetic` array and `aesthetic_model`.
  - §10: `autocut embed` also scores aesthetics.
  - §15 M4b: aesthetic done 2026-09-28.
- `CHANGELOG.md` under `## [Unreleased]`:
  - `### Added`: one bullet ending "(issue #96, ADR 15)";
  - `### Fixed`: one bullet for the `KeyError` when `weights.aesthetic` is above 0.
- Format every Markdown file with `sjust format-md <path>`, and every Python snippet in this design with `ruff format`.

## Not touched

- The embedding model, `embed_project`'s behaviour, and tags.
- The describe request and prompt. Describe still asks for the aesthetic and still wins.
- A known gap, filed separately by the architect: with local scoring off, `describe` scores only candidates, so a class with rejected segments has a `None` aesthetic and `_composite` drops the metric for the whole class. With local scoring on, every segment has a value, so the gap does not arise. Do not change `_composite`'s `None` rule here.
- A mismatch between `thumb_index` and `shot_index` after an altitude split. It is filed separately. Use `thumb_index`, as embeddings do.
- The GUI card, the sliders (the Aesthetic slider already exists), the settings dialog.
- Defaults.

## Risks / Trade-offs

- **The tower's ratings are not spread.** Say every thumbnail rates between 4.9 and 5.1. On the real Sardinia thumbnails, a working head gives a spread of a couple of points, roughly 3 to 7. Report the min, median and max from the `ai` integration test on the synthetic fixtures. The architect judges the real spread.
- **MPS half precision changes ratings.** The embedding path accepts the drift because it only compares by cosine; a linear head is more sensitive. On MPS, cast the vectors to float32 before `rate`. Do not load the tower in full precision unless a test shows a difference above 0.05 of a rating point against CPU. Report it if one does.
- **`torch.load(weights_only=True)` rejects the file.** It is a plain state dict, so it should load. If it does not, report it. Do not fall back to `weights_only=False`.
- **The profile or config snapshot tests change.** Update the snapshot only for the description change.
- **The rebase with #95's branch conflicts in `window.py`, `cache.py`, `config.py`, the snapshot, `THIRD_PARTY_LICENSES.md`, `pyproject.toml`, `SPEC.md` or `CHANGELOG.md`.** The architect resolves it at merge. Do not rebase onto the other branch.

## Verification for real

The architect runs the stage on the Sardinia thumbnails before merge. It checks:

- the spread of the ratings;
- the five highest- and five lowest-rated thumbnails, looked at by eye;
- that selection with `weights.aesthetic = 1.0` runs without the `KeyError`;
- that selection with the feature off is identical to `main`.

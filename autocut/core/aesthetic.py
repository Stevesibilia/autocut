"""A local aesthetic score per segment, from the thumbnails already in the cache.

``Metrics.aesthetic`` used to come only from the cloud ``describe`` step. This stage
fills it locally: LAION's aesthetic-predictor V1 linear head, bundled with the package,
applied to CLIP embeddings of each segment's cached thumbnail (ADR 15).

The head was trained on the vectors of OpenAI's CLIP ViT-B/32, not on the
``laion2b_s34b_b79k`` vectors the project embeds with for deduplication and tags. Those
live in a different space, so the head cannot be applied to them. The stage loads a
second tower for this alone and never touches the embedding model.

A cloud judgment always wins: the local value only fills segments the cloud has not
scored. Like embedding, the stage is optional (the ``ai`` extra) and decodes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources

import numpy as np

from autocut.core import embeddings
from autocut.core.cache import read_entry, thumb_index, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, null_progress
from autocut.core.manifest import Manifest
from autocut.core.score import rescore

#: The head is only valid for this tower, so it is a constant and not configuration.
AESTHETIC_TOWER = "ViT-B-32-quickgelu/openai"
HEAD_FILENAME = "laion_aesthetic_vit_b_32_linear.pth"
AESTHETIC_MODEL_ID = f"{AESTHETIC_TOWER}+laion-sa-0.4-linear"
#: The rating scale of the head and of the cloud judgment. Stored scaled to 0 to 1.
AESTHETIC_RANGE = (1, 10)
HEAD_DIMENSION = 512


@dataclass(slots=True)
class AestheticResult:
    """What one aesthetic pass did, for the CLI summary and the GUI."""

    model: str | None = None
    device: str | None = None
    segments: int = 0
    kept_cloud: int = 0
    files_computed: int = 0
    files_from_cache: int = 0
    skipped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


def load_head() -> tuple[np.ndarray, float]:
    """The bundled linear head as a weight vector and a bias."""
    torch = embeddings._torch()
    resource = resources.files("autocut.core").joinpath("models", HEAD_FILENAME)
    with resources.as_file(resource) as path:
        state = torch.load(path, map_location="cpu", weights_only=True)
    if set(state) != {"weight", "bias"}:
        raise ValueError(f"unexpected aesthetic head keys: {sorted(state)}")
    weight, bias = state["weight"], state["bias"]
    if tuple(weight.shape) != (1, HEAD_DIMENSION) or tuple(bias.shape) != (1,):
        raise ValueError(
            f"unexpected aesthetic head shapes: {tuple(weight.shape)}, {tuple(bias.shape)}"
        )
    return np.asarray(weight[0].float().cpu().numpy(), dtype=np.float32), float(bias[0])


def rate(vectors: np.ndarray, weight: np.ndarray, bias: float) -> np.ndarray:
    """One rating per row: the head applied to L2-normalized vectors, as LAION does."""
    if vectors.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)
    return np.asarray(embeddings.normalize(vectors) @ weight + bias, dtype=np.float32)


def _is_cloud(aesthetic: float | None, source: str | None) -> bool:
    """A cloud value, or a legacy one: before ``aesthetic_source`` only the cloud set it."""
    return aesthetic is not None and source in ("cloud", None)


def _rescore_if_weighted(manifest: Manifest, config: AutocutConfig, changed: bool) -> None:
    if changed and config.weights.aesthetic > 0:
        rescore(manifest, config.weights)


def score_aesthetics(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
) -> AestheticResult:
    """Give every segment a local aesthetic, unless the cloud already judged it."""
    if not config.providers.aesthetic:
        cleared = False
        for segment in manifest.segments.values():
            metrics = segment.metrics
            if metrics is not None and metrics.aesthetic_source == "local":
                metrics.aesthetic = None
                metrics.aesthetic_source = None
                cleared = True
        _rescore_if_weighted(manifest, config, cleared)
        return AestheticResult(skipped_reason="aesthetic scoring is disabled by configuration")
    reason = embeddings.available()
    if reason is not None:
        return AestheticResult(skipped_reason=reason)

    result = AestheticResult(model=AESTHETIC_TOWER, device=embeddings.select_device())
    segments_by_file: dict[str, list[str]] = {}
    for segment in manifest.segments.values():
        if segment.metrics is not None:
            segments_by_file.setdefault(segment.file_id, []).append(segment.id)

    changed = False
    encoder = None
    head: tuple[np.ndarray, float] | None = None
    for file_id, segment_ids in segments_by_file.items():
        entry = read_entry(file_id, config)
        if entry is None:
            result.warnings.append(f"no cache entry for {file_id}, aesthetics skipped")
            continue
        frames = entry.thumb_frames
        if frames is None or frames.size == 0:
            result.warnings.append(f"no cached frames for {file_id}, aesthetics skipped")
            continue

        stored = entry.aesthetic
        if (
            stored is not None
            and entry.aesthetic_model == AESTHETIC_MODEL_ID
            and stored.shape[0] == frames.shape[0]
        ):
            result.files_from_cache += 1
        else:
            if encoder is None:
                try:
                    encoder = embeddings.image_encoder(
                        embeddings.load_model(config, result.device, AESTHETIC_TOWER)
                    )
                    head = load_head()
                except (embeddings.EmbeddingsUnavailableError, ValueError, OSError) as exc:
                    return AestheticResult(skipped_reason=str(exc))
            assert head is not None
            vectors = embeddings.embed_frames(
                frames, encoder, config.providers.embedding_batch_size, progress
            )
            ratings = rate(vectors, *head)
            entry.aesthetic = np.clip(ratings, *AESTHETIC_RANGE).astype(np.float32)
            entry.aesthetic_model = AESTHETIC_MODEL_ID
            write_entry(entry, config)
            result.files_computed += 1

        per_shot = entry.aesthetic
        rows = 0 if per_shot is None else int(per_shot.shape[0])
        for segment_id in segment_ids:
            metrics = manifest.segments[segment_id].metrics
            index = thumb_index(segment_id, rows)
            if metrics is None or per_shot is None or index < 0:
                continue
            if _is_cloud(metrics.aesthetic, metrics.aesthetic_source):
                result.kept_cloud += 1
                continue
            value = float(per_shot[index]) / AESTHETIC_RANGE[1]
            if metrics.aesthetic != value or metrics.aesthetic_source != "local":
                changed = True
            metrics.aesthetic = value
            metrics.aesthetic_source = "local"
            result.segments += 1

    _rescore_if_weighted(manifest, config, changed)
    return result

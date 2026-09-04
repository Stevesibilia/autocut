"""One semantic embedding per segment, from the thumbnail frames already in the cache.

The classic similarity signals in :mod:`autocut.core.similarity` catch a frame filmed
twice but not the same bay filmed from two angles: on the Sardinia set the visual hash
separated whole groups by 0.08. A CLIP image embedding answers "what does this shot
show" instead of "how are its pixels arranged", which is what deduplication, tagging
and the soundtrack prompt all need.

Two properties shape this module. It is optional: torch and open_clip live in the
``ai`` extra, every import of them happens inside a function, and a machine without
them analyzes exactly as before minus one warning. And it costs no decoding: analysis
already stored one 320 px frame per shot in the cache entry, so embedding a project is
one forward pass per shot and never starts ffmpeg.

The loader returns both towers of the model. ``m3-tagging`` encodes its label set with
the text tower through the same call, so the weights are read once.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from platformdirs import user_cache_dir

from autocut.core.cache import read_entry, thumb_index, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.manifest import Manifest

MODELS_DIRNAME = "models"
NO_MODEL = "none"

#: One batch of RGB frames in, one array of vectors out. The real implementation comes
#: from :func:`image_encoder`; tests pass a deterministic function on the frame array.
Encoder = Callable[[np.ndarray], np.ndarray]

#: The other tower of the same checkpoint: prompts in, one vector per prompt out.
#: ``m3-tagging`` encodes its label set with this, so the weights are read once.
TextEncoder = Callable[[list[str]], np.ndarray]


class EmbeddingsUnavailableError(RuntimeError):
    """The ``ai`` extra is missing, or the configured model could not be loaded."""


@dataclass(slots=True)
class LoadedModel:
    """A loaded vision model and the pieces both of its towers need."""

    name: str
    architecture: str
    pretrained: str
    device: str
    model: Any
    preprocess: Any
    tokenizer: Any


@dataclass(slots=True)
class EmbedResult:
    """What one embedding pass did, for the run record and the CLI summary."""

    model: str = NO_MODEL
    device: str = NO_MODEL
    files_embedded: int = 0
    files_from_cache: int = 0
    segments: int = 0
    skipped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


def _torch() -> Any:
    """The torch module. A seam: tests replace this with a fake."""
    import torch

    return torch


def _open_clip() -> Any:
    """The open_clip module. A seam: tests replace this with a fake."""
    import open_clip

    return open_clip


_probe: tuple[bool, str | None] | None = None


def available() -> str | None:
    """``None`` when the ``ai`` extra imports, otherwise one line saying why not.

    The answer is memoized because importing torch costs seconds and both the CLI and
    ``doctor`` ask. A real import rather than a metadata check on purpose: an installed
    torch that cannot load its shared libraries is not an available torch, and the
    difference matters to the person reading the doctor report.
    """
    global _probe
    if _probe is None:
        try:
            _open_clip()
            _torch()
        except Exception as exc:  # noqa: BLE001 - a broken install is unavailability
            _probe = (False, f"the ai extra is not importable: {exc}")
        else:
            _probe = (True, None)
    return _probe[1]


def reset_availability() -> None:
    """Forget the memoized probe. For tests that install and remove the seams."""
    global _probe
    _probe = None


def select_device() -> str:
    """The best compute device for embedding: CUDA, then MPS, then CPU."""
    if available() is not None:
        return "cpu"
    torch = _torch()
    try:
        if bool(torch.cuda.is_available()):
            return "cuda"
        backend = getattr(torch.backends, "mps", None)
        if backend is not None and bool(backend.is_available()):
            return "mps"
    except Exception:  # noqa: BLE001 - a probe that raises is a device that is not there
        return "cpu"
    return "cpu"


def parse_model_name(name: str) -> tuple[str, str]:
    """Split ``architecture/pretrained`` as configured. A bare name means ``openai``."""
    architecture, _, pretrained = name.partition("/")
    return architecture, pretrained or "openai"


def models_dir(config: AutocutConfig) -> Path:
    """Where model weights are kept. Not created here: ``doctor`` only reads it."""
    base = config.cache.dir or Path(user_cache_dir("autocut"))
    return base / MODELS_DIRNAME


def weights_present(config: AutocutConfig) -> bool:
    """Whether the configured checkpoint looks like it is already on disk.

    open_clip names its downloads after the upstream URL or the Hugging Face repo, and
    the shape of both changes between releases, so this matches the pretrained tag or
    the architecture against the cached paths with separators and case removed. A false
    negative costs one line in ``doctor`` and one download, never a wrong result.
    """
    directory = models_dir(config)
    if not directory.exists():
        return False
    architecture, pretrained = parse_model_name(config.providers.embedding_model)
    wanted = {_squash(architecture), _squash(pretrained)}
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        haystack = _squash(str(path.relative_to(directory)))
        if any(needle and needle in haystack for needle in wanted):
            return True
    return False


def _squash(text: str) -> str:
    return "".join(character for character in text.lower() if character.isalnum())


def load_model(config: AutocutConfig, device: str | None = None) -> LoadedModel:
    """Load the configured model onto the best device, downloading weights once.

    Weights land in the platform cache directory under ``models/``, which is what makes
    every later run work offline and lets the macOS bundle pre-seed them (ADR 7).
    """
    reason = available()
    if reason is not None:
        raise EmbeddingsUnavailableError(reason)
    open_clip = _open_clip()
    architecture, pretrained = parse_model_name(config.providers.embedding_model)
    directory = models_dir(config)
    directory.mkdir(parents=True, exist_ok=True)
    resolved = device or select_device()
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            architecture, pretrained=pretrained, cache_dir=str(directory)
        )
        tokenizer = open_clip.get_tokenizer(architecture)
        model = model.to(resolved)
        # MPS is fastest in half precision and the vectors are only ever compared by
        # cosine, so the drift against the CPU path does not reach a decision.
        if resolved == "mps":
            model = model.half()
        model.eval()
    except Exception as exc:  # noqa: BLE001 - any failure here is the same to the caller
        raise EmbeddingsUnavailableError(
            f"could not load {config.providers.embedding_model}: {exc}"
        ) from exc
    return LoadedModel(
        name=config.providers.embedding_model,
        architecture=architecture,
        pretrained=pretrained,
        device=resolved,
        model=model,
        preprocess=preprocess,
        tokenizer=tokenizer,
    )


def image_encoder(loaded: LoadedModel) -> Encoder:
    """An encoder that turns a batch of RGB frames into unnormalized vectors."""
    torch = _torch()
    from PIL import Image

    def encode(batch: np.ndarray) -> np.ndarray:
        images = [
            loaded.preprocess(Image.fromarray(np.ascontiguousarray(frame), mode="RGB"))
            for frame in batch
        ]
        stacked = torch.stack(images).to(loaded.device)
        if loaded.device == "mps":
            stacked = stacked.half()
        with torch.no_grad():
            features = loaded.model.encode_image(stacked)
        return np.asarray(features.float().cpu().numpy(), dtype=np.float32)

    return encode


def text_encoder(loaded: LoadedModel) -> TextEncoder:
    """An encoder over prompt strings, using the text tower of the loaded model."""
    torch = _torch()

    def encode(prompts: list[str]) -> np.ndarray:
        tokens = loaded.tokenizer(list(prompts)).to(loaded.device)
        with torch.no_grad():
            features = loaded.model.encode_text(tokens)
        return np.asarray(features.float().cpu().numpy(), dtype=np.float32)

    return encode


def embed_frames(
    frames: np.ndarray,
    encoder: Encoder,
    batch_size: int = 16,
    progress: ProgressCallback = null_progress,
) -> np.ndarray:
    """Encode every frame in batches and return one normalized vector per frame.

    Normalization happens here rather than at comparison time so a cosine similarity is
    a dot product and every consumer gets the same convention.
    """
    count = int(frames.shape[0]) if frames.ndim > 0 else 0
    if count == 0:
        return np.zeros((0, 0), dtype=np.float32)
    size = max(1, batch_size)
    total = math.ceil(count / size)
    outputs: list[np.ndarray] = []
    for index, start in enumerate(range(0, count, size), start=1):
        vectors = np.asarray(encoder(frames[start : start + size]), dtype=np.float32)
        outputs.append(np.atleast_2d(vectors))
        progress(ProgressEvent(stage="embed", current=index, total=total))
    return normalize(np.concatenate(outputs, axis=0))


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Scale each row to unit length, leaving a zero row alone."""
    if vectors.size == 0:
        return vectors.astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return np.asarray(vectors / norms, dtype=np.float32)


def embed_project(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
) -> EmbedResult:
    """Fill in missing embeddings for every segment, from the cache alone.

    The model is loaded on first need, so a project whose files are all embedded with
    the configured model costs a directory listing and no weights read at all.
    """
    if not config.providers.local_embeddings:
        return EmbedResult(skipped_reason="embeddings are disabled by configuration")
    reason = available()
    if reason is not None:
        return EmbedResult(skipped_reason=reason)

    name = config.providers.embedding_model
    result = EmbedResult(model=name, device=select_device())
    segments_by_file: dict[str, list[str]] = {}
    for segment in manifest.segments.values():
        segments_by_file.setdefault(segment.file_id, []).append(segment.id)
    if not segments_by_file:
        return result

    encoder: Encoder | None = None
    for file_id, segment_ids in segments_by_file.items():
        entry = read_entry(file_id, config)
        if entry is None:
            result.warnings.append(f"no cache entry for {file_id}, embeddings skipped")
            continue
        frames = entry.thumb_frames
        if frames is None or frames.size == 0:
            result.warnings.append(f"no cached frames for {file_id}, embeddings skipped")
            continue

        stored = entry.embeddings
        fresh = (
            stored is not None
            and entry.embedding_model == name
            and stored.shape[0] == frames.shape[0]
        )
        if fresh:
            result.files_from_cache += 1
        else:
            if encoder is None:
                try:
                    encoder = image_encoder(load_model(config, result.device))
                except EmbeddingsUnavailableError as exc:
                    return EmbedResult(skipped_reason=str(exc))
            entry.embeddings = embed_frames(
                frames, encoder, config.providers.embedding_batch_size, progress
            )
            entry.embedding_model = name
            write_entry(entry, config)
            result.files_embedded += 1

        vectors = entry.embeddings
        available_rows = 0 if vectors is None else int(vectors.shape[0])
        for segment_id in segment_ids:
            index = thumb_index(segment_id, available_rows)
            if index < 0:
                continue
            manifest.segments[segment_id].embedding_ref = f"{file_id}:{index}"
            result.segments += 1
    return result

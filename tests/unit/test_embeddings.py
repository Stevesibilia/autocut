"""Embeddings: availability, device choice, batching and what the cache remembers.

Every test here runs without torch. The module exposes ``_torch`` and ``_open_clip`` as
seams and takes its encoder as an argument, so the mechanics are testable on a machine
without the ai extra; the real model is exercised by the ``ai`` marked integration test.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from autocut.core import embeddings
from autocut.core.cache import CacheEntry, read_entry, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.embeddings import (
    EmbedResult,
    embed_frames,
    embed_project,
    normalize,
    parse_model_name,
    weights_present,
)
from autocut.core.events import ProgressEvent
from autocut.core.manifest import Manifest, Segment

MODEL = "ViT-B-32/laion2b_s34b_b79k"
OTHER_MODEL = "ViT-L-14/laion2b_s32b_b82k"


@pytest.fixture(autouse=True)
def forget_the_probe() -> Any:
    """The availability probe is memoized for the process; each test starts clean."""
    embeddings.reset_availability()
    yield
    embeddings.reset_availability()


def config_in(tmp_path: Path, model: str = MODEL) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    # Pinned separately from the analysis cache, which is the point of the field: a
    # checkpoint belongs to the machine and must not follow a per project cache dir.
    config.cache.models_dir = tmp_path / "models-root"
    config.providers.embedding_model = model
    return config


def frames(count: int, seed: int = 0) -> np.ndarray:
    """Distinct 8x8 RGB frames, so distinct frames give distinct vectors."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(count, 8, 8, 3), dtype=np.uint8)


class FakeEncoder:
    """A deterministic stand-in for the vision tower that counts its batches."""

    def __init__(self, dimension: int = 4, scale: float = 1.0) -> None:
        self.dimension = dimension
        self.scale = scale
        self.batches: list[int] = []

    def __call__(self, batch: np.ndarray) -> np.ndarray:
        self.batches.append(int(batch.shape[0]))
        flat = batch.reshape(batch.shape[0], -1).astype(np.float64)
        columns = [
            flat.mean(axis=1),
            flat.std(axis=1),
            flat[:, 0],
            flat[:, -1],
        ][: self.dimension]
        return np.stack(columns, axis=1).astype(np.float32) * self.scale


def entry_with(key: str, count: int, seed: int = 0) -> CacheEntry:
    return CacheEntry(
        file_key=key,
        source="original",
        arrays={
            "timestamps": np.arange(count * 2, dtype=np.float64) / 2.0,
            "motion": np.full(count * 2, 0.2),
        },
        shot_bounds=[(float(i), float(i + 1)) for i in range(count)],
        thumb_frames=frames(count, seed),
    )


def manifest_for(tmp_path: Path, keys: dict[str, int]) -> Manifest:
    """A manifest with ``count`` segments per file key, ids shaped like the real ones."""
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "out"
    )
    for key, count in keys.items():
        for index in range(count):
            segment_id = f"{key}:{index}"
            manifest.segments[segment_id] = Segment(
                id=segment_id, file_id=key, start_s=float(index), end_s=float(index) + 1.0
            )
    return manifest


def available_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_probe", (True, None))


def encoder_returning(monkeypatch: pytest.MonkeyPatch, encoder: FakeEncoder) -> None:
    """Replace the model load and the real encoder with the fake one."""
    monkeypatch.setattr(embeddings, "load_model", lambda config, device=None, name=None: object())
    monkeypatch.setattr(embeddings, "image_encoder", lambda loaded: encoder)


def test_availability_reports_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> Any:
        raise ImportError("No module named 'torch'")

    monkeypatch.setattr(embeddings, "_torch", missing)
    monkeypatch.setattr(embeddings, "_open_clip", lambda: object())
    reason = embeddings.available()
    assert reason is not None
    assert "torch" in reason


def test_availability_is_none_when_both_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_torch", lambda: object())
    monkeypatch.setattr(embeddings, "_open_clip", lambda: object())
    assert embeddings.available() is None


class FakeBackend:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


class FakeTorch:
    def __init__(self, cuda: bool = False, mps: bool = False) -> None:
        self.cuda = FakeBackend(cuda)
        self.backends = type("Backends", (), {"mps": FakeBackend(mps)})()


@pytest.mark.parametrize(
    ("cuda", "mps", "expected"),
    [(True, True, "cuda"), (False, True, "mps"), (False, False, "cpu")],
)
def test_device_order_is_cuda_then_mps_then_cpu(
    monkeypatch: pytest.MonkeyPatch, cuda: bool, mps: bool, expected: str
) -> None:
    available_extra(monkeypatch)
    monkeypatch.setattr(embeddings, "_torch", lambda: FakeTorch(cuda=cuda, mps=mps))
    assert embeddings.select_device() == expected


def test_the_device_is_cpu_without_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_probe", (False, "no torch"))
    assert embeddings.select_device() == "cpu"


def test_model_names_split_into_architecture_and_pretrained() -> None:
    assert parse_model_name(MODEL) == ("ViT-B-32", "laion2b_s34b_b79k")
    assert parse_model_name("ViT-B-32") == ("ViT-B-32", "openai")


def test_embedded_vectors_are_normalized_and_one_per_frame() -> None:
    encoder = FakeEncoder(scale=250.0)
    vectors = embed_frames(frames(5), encoder, batch_size=2)
    assert vectors.shape == (5, 4)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6)


def test_one_progress_event_per_batch() -> None:
    """Sixty frames in batches of sixteen is four batches, so four events."""
    events: list[ProgressEvent] = []
    encoder = FakeEncoder()
    embed_frames(frames(60), encoder, batch_size=16, progress=events.append)
    assert len(events) == 4
    assert encoder.batches == [16, 16, 16, 12]
    assert [event.current for event in events] == [1, 2, 3, 4]
    assert {event.total for event in events} == {4}
    assert {event.stage for event in events} == {"embed"}


def test_no_frames_gives_no_vectors() -> None:
    encoder = FakeEncoder()
    vectors = embed_frames(np.zeros((0, 8, 8, 3), dtype=np.uint8), encoder)
    assert vectors.shape[0] == 0
    assert encoder.batches == []


def test_a_zero_vector_survives_normalization() -> None:
    assert np.allclose(normalize(np.zeros((1, 3), dtype=np.float32)), 0.0)


def test_disabled_by_configuration_loads_nothing(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    config.providers.local_embeddings = False
    manifest = manifest_for(tmp_path, {"aaa": 2})

    result = embed_project(manifest, config)
    assert result.skipped
    assert result.skipped_reason is not None
    assert "disabled" in result.skipped_reason
    assert result.model == "none"
    assert manifest.segments["aaa:0"].embedding_ref is None


def test_a_missing_extra_skips_without_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(embeddings, "_probe", (False, "the ai extra is not importable: no torch"))
    manifest = manifest_for(tmp_path, {"aaa": 2})

    result = embed_project(manifest, config_in(tmp_path))
    assert result.skipped
    assert result.model == "none"
    assert result.device == "none"


def test_embedding_fills_refs_and_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    available_extra(monkeypatch)
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")
    encoder = FakeEncoder()
    encoder_returning(monkeypatch, encoder)
    write_entry(entry_with("aaa", 3), config)
    manifest = manifest_for(tmp_path, {"aaa": 3})

    result = embed_project(manifest, config)
    assert not result.skipped
    assert result.files_embedded == 1
    assert result.files_from_cache == 0
    assert result.segments == 3
    assert result.model == MODEL
    assert result.device == "cpu"
    assert [manifest.segments[f"aaa:{i}"].embedding_ref for i in range(3)] == [
        "aaa:0",
        "aaa:1",
        "aaa:2",
    ]

    stored = read_entry("aaa", config)
    assert stored is not None
    assert stored.embedding_model == MODEL
    assert stored.embeddings is not None
    assert stored.embeddings.shape == (3, 4)


def test_a_second_run_with_the_same_model_recomputes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    available_extra(monkeypatch)
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")
    encoder = FakeEncoder()
    encoder_returning(monkeypatch, encoder)
    write_entry(entry_with("aaa", 3), config)
    manifest = manifest_for(tmp_path, {"aaa": 3})

    embed_project(manifest, config)
    first_pass = list(encoder.batches)
    second = embed_project(manifest, config)

    assert encoder.batches == first_pass
    assert second.files_embedded == 0
    assert second.files_from_cache == 1
    assert second.segments == 3


def test_changing_the_model_recomputes_without_touching_the_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    available_extra(monkeypatch)
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")
    encoder = FakeEncoder()
    encoder_returning(monkeypatch, encoder)
    write_entry(entry_with("aaa", 3), config)
    manifest = manifest_for(tmp_path, {"aaa": 3})
    embed_project(manifest, config)
    metrics_before = read_entry("aaa", config)
    assert metrics_before is not None

    other = config_in(tmp_path, OTHER_MODEL)
    encoder.batches.clear()
    result = embed_project(manifest, other)

    assert result.files_embedded == 1
    assert encoder.batches == [3]
    stored = read_entry("aaa", other)
    assert stored is not None
    assert stored.embedding_model == OTHER_MODEL
    # The point of keying embeddings by model: a decode is not paid for again.
    assert np.allclose(stored.arrays["motion"], metrics_before.arrays["motion"])
    assert np.allclose(stored.arrays["timestamps"], metrics_before.arrays["timestamps"])
    assert stored.thumb_frames is not None
    assert metrics_before.thumb_frames is not None
    assert np.array_equal(stored.thumb_frames, metrics_before.thumb_frames)


def test_embedding_starts_no_ffmpeg_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of embedding from the cache: no video is decoded again."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a subprocess was started: {args!r}")

    config = config_in(tmp_path)
    available_extra(monkeypatch)
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")
    encoder_returning(monkeypatch, FakeEncoder())
    write_entry(entry_with("aaa", 2), config)
    manifest = manifest_for(tmp_path, {"aaa": 2})
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    assert embed_project(manifest, config).segments == 2


def test_a_file_without_a_cache_entry_warns_and_carries_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    available_extra(monkeypatch)
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")
    encoder_returning(monkeypatch, FakeEncoder())
    write_entry(entry_with("aaa", 2), config)
    manifest = manifest_for(tmp_path, {"aaa": 2, "bbb": 1})

    result = embed_project(manifest, config)
    assert result.segments == 2
    assert result.warnings == ["no cache entry for bbb, embeddings skipped"]
    assert manifest.segments["bbb:0"].embedding_ref is None


def test_segments_split_out_of_one_shot_share_its_vector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An altitude split makes two segments of one shot, and one frame was cached."""
    config = config_in(tmp_path)
    available_extra(monkeypatch)
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")
    encoder_returning(monkeypatch, FakeEncoder())
    write_entry(entry_with("aaa", 1), config)
    manifest = manifest_for(tmp_path, {"aaa": 3})

    result = embed_project(manifest, config)
    assert result.segments == 3
    assert {manifest.segments[f"aaa:{i}"].embedding_ref for i in range(3)} == {"aaa:0"}


def test_weights_are_reported_missing_before_the_first_download(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    assert not weights_present(config)
    directory = embeddings.models_dir(config)
    assert directory == tmp_path / "models-root" / "models"
    assert not directory.exists()


def test_the_model_directory_does_not_follow_the_analysis_cache(tmp_path: Path) -> None:
    """A 350 MB checkpoint must not be downloaded again for every project."""
    config = AutocutConfig()
    config.cache.dir = tmp_path / "one-project"

    assert tmp_path / "one-project" not in embeddings.models_dir(config).parents


def test_weights_are_found_by_the_pretrained_tag(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    directory = embeddings.models_dir(config)
    repo = directory / "models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K" / "snapshots" / "a1"
    repo.mkdir(parents=True)
    (repo / "open_clip_pytorch_model.bin").write_bytes(b"weights")
    assert weights_present(config)


def test_weights_are_found_by_the_architecture_for_openai_checkpoints(tmp_path: Path) -> None:
    config = config_in(tmp_path, "ViT-B-32")
    directory = embeddings.models_dir(config)
    directory.mkdir(parents=True)
    (directory / "ViT-B-32.pt").write_bytes(b"weights")
    assert weights_present(config)


def test_an_empty_result_reports_no_model() -> None:
    assert EmbedResult().model == "none"
    assert not EmbedResult().skipped


def test_weights_present_takes_another_model_name(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    directory = embeddings.models_dir(config)
    directory.mkdir(parents=True)
    repo = directory / "models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K" / "snapshots" / "a1"
    repo.mkdir(parents=True)
    (repo / "open_clip_pytorch_model.bin").write_bytes(b"weights")
    assert weights_present(config)
    assert not weights_present(config, "ViT-B-32-quickgelu/openai")
    (directory / "ViT-B-32-quickgelu-openai.bin").write_bytes(b"weights")
    assert weights_present(config, "ViT-B-32-quickgelu/openai")


class FakeOpenClip:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []

    def create_model_and_transforms(
        self, architecture: str, pretrained: str, cache_dir: str
    ) -> tuple[Any, None, str]:
        self.created.append((architecture, pretrained))
        return FakeModel(), None, "preprocess"

    def get_tokenizer(self, architecture: str) -> str:
        return "tokenizer"


class FakeModel:
    def to(self, device: str) -> FakeModel:
        return self

    def eval(self) -> None:
        return None


def test_load_model_defaults_to_the_configured_model_and_takes_a_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_in(tmp_path)
    fake = FakeOpenClip()
    monkeypatch.setattr(embeddings, "_probe", (True, None))
    monkeypatch.setattr(embeddings, "_open_clip", lambda: fake)

    default = embeddings.load_model(config, "cpu")
    other = embeddings.load_model(config, "cpu", "ViT-B-32-quickgelu/openai")

    assert default.name == MODEL
    assert other.name == "ViT-B-32-quickgelu/openai"
    assert fake.created == [
        ("ViT-B-32", "laion2b_s34b_b79k"),
        ("ViT-B-32-quickgelu", "openai"),
    ]

"""Local aesthetic scoring: the head, the stage, the cache and who wins.

Every test runs without torch. The stage reaches the model through the seams of
:mod:`autocut.core.embeddings`, and the encoder here is a deterministic function on the
frame array; the real tower and head are exercised by the ``ai`` marked integration test.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from autocut.core import aesthetic, embeddings
from autocut.core.aesthetic import (
    AESTHETIC_MODEL_ID,
    AESTHETIC_RANGE,
    AESTHETIC_TOWER,
    HEAD_FILENAME,
    load_head,
    rate,
    score_aesthetics,
)
from autocut.core.cache import CacheEntry, read_entry, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Metrics, Segment, SourceFile

HEAD_SHA256 = "c7b14cead230694acc7b9447974d3cad78003c72da032e402a303b6c2429e85f"


@pytest.fixture(autouse=True)
def forget_the_probe() -> Any:
    embeddings.reset_availability()
    yield
    embeddings.reset_availability()


class FakeHead:
    """A rating equal to the first component of the normalized vector, times ten."""

    def __init__(self) -> None:
        self.weight = np.zeros(4, dtype=np.float32)
        self.weight[0] = 10.0


class FakeEncoder:
    def __init__(self) -> None:
        self.batches: list[int] = []

    def __call__(self, batch: np.ndarray) -> np.ndarray:
        self.batches.append(int(batch.shape[0]))
        flat = batch.reshape(batch.shape[0], -1).astype(np.float64)
        columns = [flat.mean(axis=1), flat.std(axis=1), flat[:, 0], flat[:, -1]]
        return np.stack(columns, axis=1).astype(np.float32)


class Seams:
    """The model load and head load, replaced, with a record of what was asked."""

    def __init__(self) -> None:
        self.encoder = FakeEncoder()
        self.loads: list[str | None] = []


def config_in(tmp_path: Path, *, enabled: bool = True, weight: float = 0.0) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    config.cache.models_dir = tmp_path / "models-root"
    config.providers.aesthetic = enabled
    config.weights.aesthetic = weight
    return config


def install(monkeypatch: pytest.MonkeyPatch) -> Seams:
    seams = Seams()
    monkeypatch.setattr(embeddings, "_probe", (True, None))
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")

    def load(config: AutocutConfig, device: str | None = None, name: str | None = None) -> object:
        seams.loads.append(name)
        return object()

    monkeypatch.setattr(embeddings, "load_model", load)
    monkeypatch.setattr(embeddings, "image_encoder", lambda loaded: seams.encoder)
    monkeypatch.setattr(aesthetic, "load_head", lambda: (FakeHead().weight, 0.0))
    return seams


def entry_with(key: str, count: int) -> CacheEntry:
    rng = np.random.default_rng(3)
    return CacheEntry(
        file_key=key,
        source="original",
        arrays={"timestamps": np.arange(count * 2) / 2.0, "motion": np.full(count * 2, 0.2)},
        shot_bounds=[(float(i), float(i + 1)) for i in range(count)],
        thumb_frames=rng.integers(0, 255, size=(count, 8, 8, 3), dtype=np.uint8),
    )


def manifest_for(tmp_path: Path, keys: dict[str, int]) -> Manifest:
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "out"
    )
    for key, count in keys.items():
        manifest.files[key] = SourceFile(
            id=key,
            path=tmp_path / f"{key}.MP4",
            source_class="drone",
            duration_s=30.0,
            width=1920,
            height=1080,
            fps=25.0,
            codec="h264",
            pix_fmt="yuv420p",
        )
        for index in range(count):
            segment_id = f"{key}:{index}"
            manifest.segments[segment_id] = Segment(
                id=segment_id,
                file_id=key,
                start_s=float(index),
                end_s=float(index) + 1.0,
                metrics=Metrics(
                    sharpness=100.0 + index,
                    exposure_clipped=0.0,
                    motion=0.3,
                    stability=0.9,
                    colorfulness=0.2,
                ),
            )
    return manifest


def test_rate_is_the_normalized_dot_product_plus_the_bias() -> None:
    vectors = np.array([[3.0, 4.0], [0.0, 2.0]], dtype=np.float32)
    weight = np.array([10.0, 5.0], dtype=np.float32)
    # Normalized rows are (0.6, 0.8) and (0, 1): 6 + 4 + 0.5 and 5 + 0.5.
    assert rate(vectors, weight, 0.5) == pytest.approx([10.5, 5.5])


def test_rate_of_no_vectors_is_empty() -> None:
    assert rate(np.zeros((0, 2), dtype=np.float32), np.zeros(2, dtype=np.float32), 1.0).size == 0


def test_the_bundled_head_is_the_published_file() -> None:
    path = resources.files("autocut.core").joinpath("models", HEAD_FILENAME)
    data = path.read_bytes()
    assert len(data) == 3047
    assert hashlib.sha256(data).hexdigest() == HEAD_SHA256


def test_the_licence_travels_with_the_head() -> None:
    licence = resources.files("autocut.core").joinpath("models", "LAION-AESTHETIC-LICENSE.txt")
    assert licence.read_text(encoding="utf-8").startswith("MIT License")


class FakeTensor:
    def __init__(self, array: np.ndarray) -> None:
        self.array = array
        self.shape = array.shape

    def __getitem__(self, index: int) -> FakeTensor:
        return FakeTensor(self.array[index])

    def float(self) -> FakeTensor:
        return self

    def cpu(self) -> FakeTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self.array

    def __float__(self) -> float:
        return float(self.array)


class FakeTorch:
    def __init__(self, state: dict[str, FakeTensor]) -> None:
        self.state = state
        self.kwargs: dict[str, Any] = {}

    def load(self, path: Any, **kwargs: Any) -> dict[str, FakeTensor]:
        self.kwargs = kwargs
        return self.state


def test_the_head_loads_with_weights_only(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "weight": FakeTensor(np.ones((1, 512), dtype=np.float32)),
        "bias": FakeTensor(np.array([2.5], dtype=np.float32)),
    }
    torch = FakeTorch(state)
    monkeypatch.setattr(embeddings, "_torch", lambda: torch)
    weight, bias = load_head()
    assert weight.shape == (512,)
    assert bias == 2.5
    assert torch.kwargs == {"map_location": "cpu", "weights_only": True}


def test_a_head_with_the_wrong_shape_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "weight": FakeTensor(np.ones((1, 768), dtype=np.float32)),
        "bias": FakeTensor(np.zeros(1, dtype=np.float32)),
    }
    monkeypatch.setattr(embeddings, "_torch", lambda: FakeTorch(state))
    with pytest.raises(ValueError, match="shapes"):
        load_head()


def test_the_tower_is_the_quickgelu_openai_one() -> None:
    assert AESTHETIC_TOWER == "ViT-B-32-quickgelu/openai"
    assert AutocutConfig().providers.embedding_model != AESTHETIC_TOWER


def test_local_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seams = install(monkeypatch)
    config = config_in(tmp_path)
    write_entry(entry_with("aaa", 3), config)
    manifest = manifest_for(tmp_path, {"aaa": 3})

    result = score_aesthetics(manifest, config)

    assert not result.skipped
    assert result.model == AESTHETIC_TOWER
    assert result.device == "cpu"
    assert result.segments == 3
    assert result.files_computed == 1
    assert seams.loads == [AESTHETIC_TOWER]
    for segment in manifest.segments.values():
        assert segment.metrics is not None
        assert segment.metrics.aesthetic_source == "local"
        assert 0.1 <= (segment.metrics.aesthetic or 0.0) <= 1.0
    stored = read_entry("aaa", config)
    assert stored is not None
    assert stored.aesthetic is not None
    assert stored.aesthetic.shape == (3,)
    assert stored.aesthetic_model == AESTHETIC_MODEL_ID
    # The embedding fields belong to the other tower and are left alone.
    assert stored.embeddings is None


def test_ratings_are_clipped_to_the_scale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch)
    huge = np.array([1000.0, 0.0, 0.0, 0.0], dtype=np.float32)
    monkeypatch.setattr(aesthetic, "load_head", lambda: (huge, -5000.0))
    config = config_in(tmp_path)
    write_entry(entry_with("aaa", 2), config)
    manifest = manifest_for(tmp_path, {"aaa": 2})

    score_aesthetics(manifest, config)

    stored = read_entry("aaa", config)
    assert stored is not None and stored.aesthetic is not None
    assert stored.aesthetic.min() == AESTHETIC_RANGE[0]
    for segment in manifest.segments.values():
        assert segment.metrics is not None
        assert segment.metrics.aesthetic == pytest.approx(AESTHETIC_RANGE[0] / AESTHETIC_RANGE[1])


def test_cloud_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch)
    config = config_in(tmp_path)
    write_entry(entry_with("aaa", 2), config)
    manifest = manifest_for(tmp_path, {"aaa": 2})
    cloud = manifest.segments["aaa:0"].metrics
    assert cloud is not None
    cloud.aesthetic, cloud.aesthetic_source = 0.9, "cloud"

    first = score_aesthetics(manifest, config)
    again = score_aesthetics(manifest, config)

    assert cloud.aesthetic == 0.9 and cloud.aesthetic_source == "cloud"
    assert first.kept_cloud == again.kept_cloud == 1
    assert first.segments == 1
    other = manifest.segments["aaa:1"].metrics
    assert other is not None and other.aesthetic_source == "local"


def test_a_legacy_value_is_a_cloud_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch)
    config = config_in(tmp_path)
    write_entry(entry_with("aaa", 1), config)
    manifest = manifest_for(tmp_path, {"aaa": 1})
    metrics = manifest.segments["aaa:0"].metrics
    assert metrics is not None
    metrics.aesthetic = 0.4

    result = score_aesthetics(manifest, config)

    assert metrics.aesthetic == 0.4
    assert metrics.aesthetic_source is None
    assert result.kept_cloud == 1 and result.segments == 0


def test_cached_ratings_load_no_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seams = install(monkeypatch)
    config = config_in(tmp_path)
    write_entry(entry_with("aaa", 3), config)
    manifest = manifest_for(tmp_path, {"aaa": 3})

    score_aesthetics(manifest, config)
    batches, loads = list(seams.encoder.batches), list(seams.loads)
    second = score_aesthetics(manifest, config)

    assert seams.encoder.batches == batches
    assert seams.loads == loads
    assert second.files_computed == 0
    assert second.files_from_cache == 1
    assert second.segments == 3


def test_ratings_from_another_model_id_are_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seams = install(monkeypatch)
    config = config_in(tmp_path)
    entry = entry_with("aaa", 2)
    entry.aesthetic = np.array([5.0, 5.0], dtype=np.float32)
    entry.aesthetic_model = "something-else"
    write_entry(entry, config)

    result = score_aesthetics(manifest_for(tmp_path, {"aaa": 2}), config)

    assert result.files_computed == 1
    assert len(seams.loads) == 1


def test_turned_off_removes_local_values_and_loads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seams = install(monkeypatch)
    on = config_in(tmp_path)
    write_entry(entry_with("aaa", 2), on)
    manifest = manifest_for(tmp_path, {"aaa": 2})
    cloud = manifest.segments["aaa:0"].metrics
    assert cloud is not None
    cloud.aesthetic, cloud.aesthetic_source = 0.9, "cloud"
    score_aesthetics(manifest, on)
    loads = list(seams.loads)

    result = score_aesthetics(manifest, config_in(tmp_path, enabled=False))

    assert result.skipped_reason == "aesthetic scoring is disabled by configuration"
    assert result.segments == 0
    assert seams.loads == loads
    assert cloud.aesthetic == 0.9 and cloud.aesthetic_source == "cloud"
    local = manifest.segments["aaa:1"].metrics
    assert local is not None
    assert local.aesthetic is None and local.aesthetic_source is None


def test_a_missing_extra_leaves_existing_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(embeddings, "_probe", (False, "the ai extra is not importable: nope"))
    manifest = manifest_for(tmp_path, {"aaa": 1})
    metrics = manifest.segments["aaa:0"].metrics
    assert metrics is not None
    metrics.aesthetic, metrics.aesthetic_source = 0.5, "local"

    result = score_aesthetics(manifest, config_in(tmp_path))

    assert result.skipped_reason == "the ai extra is not importable: nope"
    assert metrics.aesthetic == 0.5


def test_a_file_without_a_cache_entry_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    result = score_aesthetics(manifest_for(tmp_path, {"gone": 1}), config_in(tmp_path))
    assert result.warnings == ["no cache entry for gone, aesthetics skipped"]
    assert result.segments == 0


def test_a_split_segment_shares_its_shots_rating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    config = config_in(tmp_path)
    write_entry(entry_with("aaa", 1), config)
    manifest = manifest_for(tmp_path, {"aaa": 2})

    score_aesthetics(manifest, config)

    first, second = (manifest.segments[f"aaa:{i}"].metrics for i in range(2))
    assert first is not None and second is not None
    assert first.aesthetic == second.aesthetic


def scores(manifest: Manifest) -> list[float | None]:
    return [segment.score for segment in manifest.segments.values()]


def test_scores_are_recomputed_only_when_the_weight_is_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    calls: list[float] = []

    def spy(manifest: Manifest, weights: Any) -> int:
        calls.append(weights.aesthetic)
        return 0

    monkeypatch.setattr(aesthetic, "rescore", spy)
    write_entry(entry_with("aaa", 2), config_in(tmp_path))

    score_aesthetics(manifest_for(tmp_path, {"aaa": 2}), config_in(tmp_path, weight=0.0))
    assert calls == []

    manifest = manifest_for(tmp_path, {"aaa": 2})
    weighted = config_in(tmp_path, weight=1.0)
    score_aesthetics(manifest, weighted)
    assert calls == [1.0]

    # Nothing changed on the second run, so nothing is scored again.
    score_aesthetics(manifest, weighted)
    assert calls == [1.0]


def test_turning_the_feature_off_rescores_when_weighted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    calls: list[float] = []
    monkeypatch.setattr(aesthetic, "rescore", lambda manifest, weights: calls.append(1) or 0)
    write_entry(entry_with("aaa", 1), config_in(tmp_path))
    manifest = manifest_for(tmp_path, {"aaa": 1})
    score_aesthetics(manifest, config_in(tmp_path))

    score_aesthetics(manifest, config_in(tmp_path, enabled=False, weight=1.0))
    assert calls == [1]

    score_aesthetics(manifest, config_in(tmp_path, enabled=False, weight=1.0))
    assert calls == [1]


def test_a_weighted_aesthetic_moves_the_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    config = config_in(tmp_path, weight=5.0)
    write_entry(entry_with("aaa", 3), config)
    manifest = manifest_for(tmp_path, {"aaa": 3})
    before = scores(manifest)

    score_aesthetics(manifest, config)

    assert scores(manifest) != before
    assert all(score is not None for score in scores(manifest))


def test_the_cache_round_trips_the_ratings(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    entry = entry_with("aaa", 2)
    entry.aesthetic = np.array([4.5, 6.25], dtype=np.float32)
    entry.aesthetic_model = AESTHETIC_MODEL_ID
    write_entry(entry, config)

    stored = read_entry("aaa", config)

    assert stored is not None
    assert stored.aesthetic is not None
    assert stored.aesthetic.tolist() == [4.5, 6.25]
    assert stored.aesthetic_model == AESTHETIC_MODEL_ID


def test_an_entry_without_ratings_reads_back_without(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    write_entry(entry_with("aaa", 2), config)
    stored = read_entry("aaa", config)
    assert stored is not None
    assert stored.aesthetic is None and stored.aesthetic_model is None


def test_the_source_is_optional_in_a_manifest() -> None:
    plain = {
        "sharpness": 1.0,
        "exposure_clipped": 0.0,
        "motion": 0.1,
        "stability": 0.9,
        "colorfulness": 0.2,
        "aesthetic": 0.5,
    }
    assert Metrics.model_validate(plain).aesthetic_source is None
    assert Metrics.model_validate({**plain, "aesthetic_source": "local"}).aesthetic_source == (
        "local"
    )

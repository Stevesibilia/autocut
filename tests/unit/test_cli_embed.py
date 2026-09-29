"""The embed command and the embedding step at the end of analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core import embeddings
from autocut.core.cache import CacheEntry, read_entry, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Segment

runner = CliRunner()

MODEL = "ViT-B-32/laion2b_s34b_b79k"


@pytest.fixture(autouse=True)
def forget_the_probe() -> None:
    embeddings.reset_availability()


class FakeEncoder:
    def __init__(self) -> None:
        self.batches: list[int] = []

    def __call__(self, batch: np.ndarray) -> np.ndarray:
        self.batches.append(int(batch.shape[0]))
        flat = batch.reshape(batch.shape[0], -1).astype(np.float32)
        return np.stack([flat.mean(axis=1), flat.std(axis=1)], axis=1)


def project_in(tmp_path: Path, *, local_embeddings: bool = True, shots: int = 3) -> Path:
    """A project folder with a manifest, an autocut.toml and one cached file."""
    project = tmp_path / "edit"
    project.mkdir()
    cache = tmp_path / "cache"
    (tmp_path / "autocut.toml").write_text(
        "[cache]\n"
        f'dir = "{cache.as_posix()}"\n'
        "\n[providers]\n"
        f"local_embeddings = {str(local_embeddings).lower()}\n",
        encoding="utf-8",
    )

    config = AutocutConfig()
    config.cache.dir = cache
    rng = np.random.default_rng(3)
    write_entry(
        CacheEntry(
            file_key="aaa",
            source="original",
            arrays={"timestamps": np.arange(shots * 2, dtype=np.float64) / 2.0},
            shot_bounds=[(float(i), float(i) + 1.0) for i in range(shots)],
            thumb_frames=rng.integers(0, 255, size=(shots, 8, 8, 3), dtype=np.uint8),
        ),
        config,
    )

    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=project)
    for index in range(shots):
        segment_id = f"aaa:{index}"
        manifest.segments[segment_id] = Segment(
            id=segment_id, file_id="aaa", start_s=float(index), end_s=float(index) + 1.0
        )
    manifest.save(project / "manifest.json")
    return project


def with_extra(monkeypatch: pytest.MonkeyPatch) -> FakeEncoder:
    encoder = FakeEncoder()
    monkeypatch.setattr(embeddings, "_probe", (True, None))
    monkeypatch.setattr(embeddings, "select_device", lambda: "cpu")
    monkeypatch.setattr(embeddings, "load_model", lambda config, device=None, name=None: object())
    monkeypatch.setattr(embeddings, "image_encoder", lambda loaded: encoder)
    return encoder


def test_embed_fills_a_project_that_was_analyzed_without_the_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    encoder = with_extra(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["embed", str(project)])

    assert result.exit_code == 0, result.stdout
    assert "Embedded 3 segments" in result.stdout
    assert MODEL in result.stdout
    assert "on cpu" in result.stdout
    assert encoder.batches == [3]

    manifest = Manifest.load(project / "manifest.json")
    assert [manifest.segments[f"aaa:{i}"].embedding_ref for i in range(3)] == [
        "aaa:0",
        "aaa:1",
        "aaa:2",
    ]
    assert manifest.analysis.embedding_model == MODEL
    assert manifest.analysis.embedding_device == "cpu"


def test_a_second_embed_run_is_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    encoder = with_extra(monkeypatch)
    monkeypatch.chdir(tmp_path)

    runner.invoke(app, ["embed", str(project)])
    encoder.batches.clear()
    result = runner.invoke(app, ["embed", str(project)])

    assert result.exit_code == 0
    assert encoder.batches == []
    assert "0 files computed, 1 from cache" in result.stdout


def test_embed_says_so_when_configuration_switched_it_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, local_embeddings=False)
    with_extra(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["embed", str(project)])

    assert result.exit_code == 0
    assert "Embeddings skipped: embeddings are disabled by configuration" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.analysis.embedding_model == "none"
    assert manifest.segments["aaa:0"].embedding_ref is None


def test_embed_says_so_without_the_extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    monkeypatch.setattr(embeddings, "_probe", (False, "the ai extra is not importable: no torch"))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["embed", str(project)])

    assert result.exit_code == 0
    assert "Embeddings skipped: the ai extra is not importable" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.analysis.embedding_model == "none"
    assert manifest.analysis.embedding_device == "none"


def test_embed_without_a_manifest_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["embed", str(tmp_path / "nowhere")])

    assert result.exit_code == 1
    assert "No manifest found" in result.stdout


def test_the_model_identifier_is_stored_beside_the_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    with_extra(monkeypatch)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["embed", str(project)])

    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    entry = read_entry("aaa", config)
    assert entry is not None
    assert entry.embedding_model == MODEL
    assert entry.embeddings is not None
    assert entry.embeddings.shape == (3, 2)

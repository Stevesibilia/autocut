"""The real vision model on the synthetic fixtures.

Marked ``ai``, so it is skipped everywhere the extra is not installed and runs in the
``dev-ai`` container, where the checkpoint lives in a named volume. Everything else
about embeddings is covered by :mod:`tests.unit.test_embeddings` with a mocked encoder;
what this test adds is the only thing a mock cannot say, namely that the model puts the
same picture near itself and a different picture far away.

Which fixtures make that measurable is not obvious, and the numbers below are measured
rather than assumed. A ``gblur`` at sigma 8 is not a softer version of a picture to
CLIP, it is a different picture: ``sharp_pan`` against ``blurred`` scores 0.833. And
every ffmpeg test pattern is "a colourful test card" to the model, so ``testsrc2``
against ``smptebars`` scores 0.799 rather than anything low. The pair that does separate
is the same pattern in two different files, 0.957, against ``mandelbrot``, 0.555, which
is a picture of something else.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.analyze import analyze_files
from autocut.core.cache import read_entry
from autocut.core.config import AutocutConfig
from autocut.core.embeddings import embed_project
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest

pytestmark = [pytest.mark.ai, pytest.mark.ffmpeg]

EMBEDDING_WIDTH = 512

# multishot is three shots in one file: testsrc2, then smptebars, then mandelbrot.
SHARP = "sharp_pan.mp4"
MULTISHOT = "multishot.mp4"
TESTSRC2_SHOT = 0
MANDELBROT_SHOT = 2


def vectors(synthetic_dir: Path, tmp_path: Path, names: list[str]) -> dict[str, np.ndarray]:
    """Analyze the named fixtures, embed them, and return the vectors per file name."""
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    sources = [synthetic_dir / name for name in names]

    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=sources, output_dir=tmp_path / "edit"
    )
    manifest.files = {source.id: source for source in ingest(sources, config)}
    analyze_files(manifest, config, lambda event: None)

    result = embed_project(manifest, config)
    assert not result.skipped, result.skipped_reason
    assert result.segments > 0

    found: dict[str, np.ndarray] = {}
    for file_id, source in manifest.files.items():
        entry = read_entry(file_id, config)
        assert entry is not None
        assert entry.embeddings is not None, f"{source.path.name} has no embeddings"
        found[source.path.name] = entry.embeddings
    return found


def test_the_same_pattern_is_near_itself_and_another_picture_is_not(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    found = vectors(synthetic_dir, tmp_path, [SHARP, MULTISHOT])
    shots = found[MULTISHOT]
    assert shots.shape[0] == 3, f"multishot split into {shots.shape[0]} shots, expected 3"

    same = float(np.dot(found[SHARP][0], shots[TESTSRC2_SHOT]))
    different = float(np.dot(shots[TESTSRC2_SHOT], shots[MANDELBROT_SHOT]))

    assert same > 0.9, f"the same pattern in two files scored {same:.3f}"
    assert different < 0.7, f"testsrc2 against mandelbrot scored {different:.3f}"
    # The gap is what the semantic signal lives on, so assert it directly.
    assert same - different > 0.2


def test_the_gap_survives_the_mapping_the_signal_applies(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    """The floor of 0.5 has to turn those cosines into a clear yes and a clear no."""
    config = AutocutConfig()
    found = vectors(synthetic_dir, tmp_path, [SHARP, MULTISHOT])
    shots = found[MULTISHOT]
    floor = config.similarity.semantic_floor

    def mapped(cosine: float) -> float:
        return float(np.clip((cosine - floor) / (1.0 - floor), 0.0, 1.0))

    same = mapped(float(np.dot(found[SHARP][0], shots[TESTSRC2_SHOT])))
    different = mapped(float(np.dot(shots[TESTSRC2_SHOT], shots[MANDELBROT_SHOT])))

    assert same > 0.7, f"the same pattern mapped to {same:.3f}"
    assert different < 0.3, f"a different picture mapped to {different:.3f}"


def test_the_vectors_are_normalized_and_have_the_expected_width(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    found = vectors(synthetic_dir, tmp_path, [SHARP, MULTISHOT])

    for name, block in found.items():
        assert block.shape[1] == EMBEDDING_WIDTH, f"{name} has width {block.shape[1]}"
        assert np.allclose(np.linalg.norm(block, axis=1), 1.0, atol=1e-4), name


def test_a_second_pass_reads_the_vectors_back_from_the_cache(
    synthetic_dir: Path, tmp_path: Path
) -> None:
    """The model is loaded once; a re-run of an embedded project computes nothing."""
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    sources = [synthetic_dir / SHARP]
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=sources, output_dir=tmp_path / "edit"
    )
    manifest.files = {source.id: source for source in ingest(sources, config)}
    analyze_files(manifest, config, lambda event: None)

    first = embed_project(manifest, config)
    second = embed_project(manifest, config)

    assert first.files_embedded == 1
    assert second.files_embedded == 0
    assert second.files_from_cache == 1
    assert second.device == first.device

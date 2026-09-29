"""The real second tower and the bundled head on the synthetic fixtures.

Marked ``ai``: it runs in the ``dev-ai`` container. Everything about the stage is covered
by :mod:`tests.unit.test_aesthetic` with a fake encoder; what only the real model can say
is that the OpenAI tower loads, the bundled head fits its 512 vectors, and the ratings
come out finite and on the 1 to 10 scale. The spread is printed, not asserted: the fixtures
are test cards, and what counts is the spread on real footage (design, risks).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.aesthetic import AESTHETIC_MODEL_ID, AESTHETIC_RANGE, score_aesthetics
from autocut.core.analyze import analyze_files
from autocut.core.cache import read_entry
from autocut.core.config import AutocutConfig
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest

pytestmark = [pytest.mark.ai, pytest.mark.ffmpeg]

FIXTURES = ["sharp_pan.mp4", "multishot.mp4", "blurred.mp4"]


def test_real_ratings_are_finite_and_on_the_scale(
    synthetic_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    config.providers.aesthetic = True
    sources = [synthetic_dir / name for name in FIXTURES]
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=sources, output_dir=tmp_path / "edit"
    )
    manifest.files = {source.id: source for source in ingest(sources, config)}
    analyze_files(manifest, config, lambda event: None)

    result = score_aesthetics(manifest, config)

    assert not result.skipped, result.skipped_reason
    assert result.segments == len(manifest.segments) > 0
    ratings: list[float] = []
    for file_id in manifest.files:
        entry = read_entry(file_id, config)
        assert entry is not None and entry.aesthetic is not None
        assert entry.aesthetic_model == AESTHETIC_MODEL_ID
        ratings.extend(float(value) for value in entry.aesthetic)
    values = np.array(ratings)
    assert np.isfinite(values).all()
    assert values.min() >= AESTHETIC_RANGE[0] and values.max() <= AESTHETIC_RANGE[1]
    for segment in manifest.segments.values():
        assert segment.metrics is not None
        assert segment.metrics.aesthetic_source == "local"
        assert 0.1 <= (segment.metrics.aesthetic or 0.0) <= 1.0
    with capsys.disabled():
        print(
            f"\naesthetic ratings n={values.size} min={values.min():.3f} "
            f"median={np.median(values):.3f} max={values.max():.3f}"
        )

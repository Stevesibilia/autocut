"""The shared pipeline: the cloud fields get recorded once, and a cancel stops early."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autocut.core.analyze import AnalysisCancelled
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Metrics, Segment
from autocut.core.providers import KEY_ENV_VAR


class FakeProvider:
    """A vision provider that is never actually asked: the segments below have no
    thumbnail and no cache entry, so ``describe_project`` records the model and skips
    straight to "no thumbnail to describe" without a request. Recording the model
    before any request is made is exactly the behaviour under test.
    """

    model = "fake/vision"

    def __enter__(self) -> FakeProvider:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def describe_frame(self, jpeg: bytes, labels: list[str], correction: str | None = None) -> None:
        raise AssertionError("no thumbnail exists for this segment; it should not be asked")


def _manifest_with_one_segment(out: Path) -> Manifest:
    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[out], output_dir=out)
    manifest.segments["aaa:0"] = Segment(
        id="aaa:0",
        file_id="aaa",
        start_s=0.0,
        end_s=1.0,
        metrics=Metrics(
            sharpness=100.0, exposure_clipped=0.0, motion=0.3, stability=0.9, colorfulness=0.2
        ),
    )
    return manifest


@pytest.fixture(autouse=True)
def no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)


def test_analyze_project_records_the_cloud_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autocut.core import pipeline

    manifest = _manifest_with_one_segment(tmp_path)
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    monkeypatch.setenv(KEY_ENV_VAR, "sk-or-v1-test")
    monkeypatch.setattr(pipeline, "OpenRouterProvider", lambda key, config: FakeProvider())

    outcome = pipeline.analyze_project(manifest, config)

    assert manifest.analysis.cloud_model == "fake/vision"
    assert manifest.analysis.cloud_requests == 0
    assert manifest.analysis.cloud_cost_usd == 0.0
    assert outcome.describe is not None
    assert outcome.describe.model == "fake/vision"


def test_a_cancelled_analysis_stops_before_embed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autocut.core import pipeline

    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path)
    config = AutocutConfig()

    def cancel(*args: object, **kwargs: object) -> None:
        raise AnalysisCancelled("stop")

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("embed must not run after a cancelled analysis")

    monkeypatch.setattr(pipeline, "analyze_files", cancel)
    monkeypatch.setattr(pipeline, "run_embed", explode)

    with pytest.raises(AnalysisCancelled):
        pipeline.analyze_project(manifest, config)

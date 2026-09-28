"""The analysis pipeline, shared by the CLI and the GUI.

Both front ends run the same stages in the same order: ingest, analyze, embed, tag,
describe. Writing it once here is what keeps the two from drifting, the way the GUI's
own copy used to (it never recorded the cloud fields the CLI did). A cancelled
analysis raises :class:`AnalysisCancelled` out of :func:`analyze_project`, before the
later stages run, in both front ends.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocut.core.analyze import AnalysisCancelled, analyze_files
from autocut.core.config import AutocutConfig
from autocut.core.describe import DescribeResult, describe_project
from autocut.core.embeddings import EmbedResult, embed_project
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest, SourceFile
from autocut.core.providers import cloud_enabled, find_key
from autocut.core.providers.openrouter import OpenRouterProvider
from autocut.core.tags import TagResult, tag_project


@dataclass(slots=True)
class AnalysisOutcome:
    """What one full analysis run did, for a front end to summarize."""

    files: int = 0
    unreadable: int = 0
    segments: int = 0
    cached_files: int = 0
    embed: EmbedResult | None = None
    tag: TagResult | None = None
    describe: DescribeResult | None = None
    interrupted: bool = False


def ingest_into(
    manifest: Manifest, config: AutocutConfig, progress: ProgressCallback = null_progress
) -> list[SourceFile]:
    """Scan and probe ``manifest.sources``, filling ``manifest.files``."""
    files = ingest(list(manifest.sources), config, progress)
    manifest.files = {source.id: source for source in files}
    return files


def run_embed(
    manifest: Manifest, config: AutocutConfig, progress: ProgressCallback = null_progress
) -> EmbedResult:
    """Embed the project and record what model and device did it."""
    result = embed_project(manifest, config, progress)
    manifest.analysis.embedding_model = result.model
    manifest.analysis.embedding_device = result.device
    return result


def run_describe(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
    *,
    no_cloud: bool = False,
) -> DescribeResult:
    """The cloud pass, or the reason there was none. Never raises for a missing key."""
    enabled, reason = cloud_enabled(config, no_cloud)
    if not enabled:
        result = DescribeResult(scope=config.providers.describe_scope, skipped_reason=reason)
    else:
        key = find_key()
        assert key is not None  # cloud_enabled already established there is one
        with OpenRouterProvider(key, config) as provider:
            result = describe_project(manifest, config, provider, progress)
    manifest.analysis.cloud_model = "none" if result.skipped else result.model
    manifest.analysis.cloud_requests = result.requests
    manifest.analysis.cloud_cost_usd = result.cost_usd
    return result


def analyze_project(
    manifest: Manifest,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
    *,
    no_cloud: bool = False,
) -> AnalysisOutcome:
    """Analyze the ingested files, then embed, tag and describe.

    ``manifest.files`` must already be filled, normally by :func:`ingest_into`. On
    :class:`AnalysisCancelled` from ``analyze_files`` the exception propagates before
    embed, tag or describe run, so a cancelled run in either front end stops at the
    same point.
    """
    outcome = AnalysisOutcome(
        files=len(manifest.files),
        unreadable=sum(1 for source in manifest.files.values() if source.error),
    )

    cached = 0

    def on_analysis(event: ProgressEvent) -> None:
        nonlocal cached
        if event.extra.get("cached"):
            cached += 1
        progress(event)

    try:
        analyze_files(manifest, config, on_analysis)
    except AnalysisCancelled:
        outcome.interrupted = True
        outcome.cached_files = cached
        outcome.segments = len(manifest.segments)
        raise

    outcome.cached_files = cached
    outcome.segments = len(manifest.segments)
    outcome.embed = run_embed(manifest, config, progress)
    outcome.tag = tag_project(manifest, config)
    outcome.describe = run_describe(manifest, config, progress, no_cloud=no_cloud)
    return outcome

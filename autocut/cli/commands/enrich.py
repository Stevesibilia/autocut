"""The ``embed``, ``tag`` and ``describe`` commands: the stages ``analyze`` also runs,
callable again on their own once a project already has files and segments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from autocut.cli import output
from autocut.cli.common import ConfigOpt, NoCloudOpt, load_config, open_project
from autocut.core.config import AutocutConfig
from autocut.core.describe import DescribeResult
from autocut.core.embeddings import EmbedResult
from autocut.core.events import ProgressEvent
from autocut.core.manifest import Manifest
from autocut.core.pipeline import run_describe, run_embed
from autocut.core.providers import cloud_enabled
from autocut.core.tags import TagResult, tag_project


def _run_embed(manifest: Manifest, cfg: AutocutConfig) -> EmbedResult:
    """Embed the project and record on the run what did it and where.

    The progress bar is built on the first event rather than up front, so a project
    that is already embedded, or a machine without the extra, prints one line and no
    empty bar.
    """
    bar: Progress | None = None
    task: TaskID | None = None

    def on_event(event: ProgressEvent) -> None:
        nonlocal bar, task
        if bar is None:
            bar = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=output.console,
            )
            bar.start()
            task = bar.add_task("Embedding", total=event.total)
        assert task is not None
        bar.update(task, completed=event.current, total=event.total)

    try:
        return run_embed(manifest, cfg, on_event)
    finally:
        if bar is not None:
            bar.stop()


def embed(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Compute the missing segment embeddings from the analysis cache."""
    cfg = load_config(config, no_cloud)
    manifest = open_project(project)
    result = _run_embed(manifest, cfg)
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    output.print_embed(result)


def _run_tag(manifest: Manifest, cfg: AutocutConfig) -> TagResult:
    """Recompute the local tags. Cheap enough that no progress bar is worth the noise."""
    return tag_project(manifest, cfg)


def tag(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Recompute the semantic tags from the cached embeddings and the label set."""
    cfg = load_config(config, no_cloud)
    manifest = open_project(project)
    result = _run_tag(manifest, cfg)
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    output.print_tag(result)


def _run_describe(manifest: Manifest, cfg: AutocutConfig, no_cloud: bool) -> DescribeResult:
    """Describe the project through the configured provider, or say why it did not.

    The bar is built only when cloud is enabled, so a run with no key or the flag off
    prints one line and no empty bar. The enabled check is repeated inside
    ``run_describe``, which is where the three cloud fields actually get recorded.
    """
    enabled, _reason = cloud_enabled(cfg, no_cloud)
    if not enabled:
        return run_describe(manifest, cfg, no_cloud=no_cloud)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=output.console,
    ) as bar:
        task = bar.add_task("Describing", total=None)

        def on_event(event: ProgressEvent) -> None:
            bar.update(task, completed=event.current, total=event.total)

        return run_describe(manifest, cfg, on_event, no_cloud=no_cloud)


def describe(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    scope: Annotated[
        str | None,
        typer.Option("--scope", help="Segments to describe: candidates or selected."),
    ] = None,
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Ask a hosted vision model for tags, a caption and an aesthetic per segment."""
    cfg = load_config(config, no_cloud)
    if scope is not None:
        if scope not in ("candidates", "selected"):
            output.console.print(f"[red]Unknown scope[/red] {scope!r}. Use candidates or selected.")
            raise typer.Exit(code=2)
        cfg.providers.describe_scope = scope  # type: ignore[assignment]
    manifest = open_project(project)
    result = _run_describe(manifest, cfg, no_cloud)
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    output.print_describe(result)

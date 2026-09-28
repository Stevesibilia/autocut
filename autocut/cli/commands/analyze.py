"""The ``analyze`` command: scan, probe, analyze, embed, tag and describe."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
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
from autocut.cli.common import ConfigOpt, NoCloudOpt, load_config, open_manifest
from autocut.core.analyze import AnalysisCancelled
from autocut.core.events import ProgressCallback, ProgressEvent
from autocut.core.pipeline import AnalysisOutcome, analyze_project, ingest_into
from autocut.core.proc import ToolMissingError
from autocut.core.report import render_report


def analyze(
    sources: Annotated[list[Path], typer.Argument(help="Source folders to scan.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output folder.")],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
    no_proxies: Annotated[
        bool, typer.Option("--no-proxies", help="Ignore .lrv and .lrf proxy files.")
    ] = False,
    workers: Annotated[
        int | None, typer.Option("--workers", help="Parallel files. Defaults to physical cores.")
    ] = None,
) -> None:
    """Scan, probe and analyze footage. Writes manifest.json and report.html."""
    cfg = load_config(config, no_cloud)
    if no_proxies:
        cfg.analysis.use_proxies = False
    if workers is not None:
        cfg.analysis.workers = workers

    manifest_path = out / "manifest.json"
    manifest = open_manifest(out, sources, cfg)
    on_event, close_bars = _stage_progress()

    try:
        files = ingest_into(manifest, cfg, on_event)
    except ToolMissingError as error:
        close_bars()
        output.console.print(f"[red]Missing tool[/red]: {error}")
        raise typer.Exit(code=1) from None

    if not files:
        close_bars()
        output.console.print("[red]No video files found[/red] in the given source folders.")
        raise typer.Exit(code=1)

    # Closed here, not just at the end: the probe bar is done and "Probed N files"
    # belongs under it, the way each stage's own bar used to close before the next
    # printed a line.
    close_bars()

    manifest.updated_at = datetime.now(UTC)
    # Saved once here so an interrupted analysis still leaves a usable file list.
    manifest.save(manifest_path)

    failed = [source for source in files if source.error]
    output.console.print(f"Probed [bold]{len(files)}[/bold] files into {manifest_path}")
    for source in failed:
        output.console.print(f"[yellow]unreadable[/yellow] {source.path}: {source.error}")

    outcome: AnalysisOutcome | None = None
    interrupted = False
    try:
        outcome = analyze_project(manifest, cfg, on_event, no_cloud=no_cloud)
    except AnalysisCancelled:
        interrupted = True
    finally:
        close_bars()

    manifest.updated_at = datetime.now(UTC)
    manifest.save(manifest_path)

    report_path = render_report(manifest, out)

    for warning in manifest.analysis.warnings:
        output.console.print(f"[yellow]{warning}[/yellow]")

    rejected = Counter(s.reason for s in manifest.segments.values() if s.reason)
    cached = manifest.analysis.files_from_cache
    output.console.print(
        f"Analyzed [bold]{len(manifest.segments)}[/bold] segments "
        f"({cached} files from cache), {sum(rejected.values())} rejected"
    )
    for reason, count in sorted(rejected.items()):
        output.console.print(f"  {reason}: {count}")
    if outcome is not None:
        assert outcome.embed is not None
        assert outcome.tag is not None
        assert outcome.describe is not None
        output.print_embed(outcome.embed)
        output.print_tag(outcome.tag)
        output.print_describe(outcome.describe)
    output.console.print(f"Report written to {report_path}")
    if interrupted:
        output.console.print(
            "[yellow]Analysis was cancelled[/yellow]; the manifest holds partial results."
        )
        raise typer.Exit(code=130)


_STAGE_LABELS = {
    "probe": "Probing",
    "analyze": "Analyzing",
    "embed": "Embedding",
    "describe": "Describing",
}


def _stage_progress() -> tuple[ProgressCallback, Callable[[], None]]:
    """One callback that opens a fresh Rich bar for each stage in turn.

    ``scan`` shares the "Probing" bar with the ``probe`` events that follow it, since a
    run gets exactly one scan event before its probe events. Each later stage change
    closes the previous bar and opens its own, so the terminal shows one bar at a time,
    as it always has, across a call that now spans ingest and the whole analysis.
    """
    stage: str | None = None
    bar: Progress | None = None
    task: TaskID | None = None

    def close() -> None:
        nonlocal stage, bar, task
        if bar is not None:
            bar.stop()
        stage = bar = task = None

    def on_event(event: ProgressEvent) -> None:
        nonlocal stage, bar, task
        this_stage = "probe" if event.stage == "scan" else event.stage
        if this_stage != stage:
            close()
            bar = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=output.console,
            )
            bar.start()
            total = None if event.stage == "scan" else event.total
            task = bar.add_task(_STAGE_LABELS.get(this_stage, this_stage.title()), total=total)
            stage = this_stage
        assert bar is not None and task is not None
        if event.stage == "scan":
            bar.update(task, total=event.total or None)
            return
        name = event.path.name if event.path else (event.message or "")
        suffix = " (cached)" if event.extra.get("cached") else ""
        bar.update(task, completed=event.current, total=event.total, description=f"{name}{suffix}")

    return on_event, close

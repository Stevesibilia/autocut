"""The ``render`` command: join the exported clips and the track. Hard cuts only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from autocut.cli import output
from autocut.cli.common import ConfigOpt, NoCloudOpt, load_config, open_project
from autocut.core.events import ProgressEvent
from autocut.core.render import render_edit
from autocut.core.report import render_report


def render(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    track: Annotated[
        Path | None,
        typer.Option("--track", help="Track to mux. Defaults to the one the edit is synced to."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Where to write. Defaults to the output folder.")
    ] = None,
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Join the exported clips and the track into one finished file. Hard cuts only."""
    cfg = load_config(config, no_cloud)
    manifest = open_project(project)
    manifest.output_dir = project

    if not any(segment.outcome == "selected" for segment in manifest.segments.values()):
        output.console.print("[red]Nothing selected[/red]. Run autocut select first.")
        raise typer.Exit(code=1)
    if track is not None and not track.exists():
        output.console.print(f"[red]No such track[/red]: {track}")
        raise typer.Exit(code=1)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=output.console,
    ) as bar:
        task = bar.add_task("Rendering", total=3)

        def on_event(event: ProgressEvent) -> None:
            name = event.path.name if event.path else event.message
            bar.update(task, completed=event.current, total=event.total, description=name)

        result = render_edit(manifest, cfg, track=track, progress=on_event, out=out)

    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    output.print_render(result)
    if not result.ok:
        raise typer.Exit(code=1)
    output.console.print(f"Report written to {render_report(manifest, project)}")

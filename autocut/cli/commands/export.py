"""The ``export`` command: cut, normalize and write the numbered clips."""

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
from autocut.core.export import export_clips
from autocut.core.ffmpeg_cmd import ExportOverrides
from autocut.core.proc import ToolMissingError
from autocut.core.render import render_edit
from autocut.core.report import render_report


def export(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    no_audio: Annotated[
        bool, typer.Option("--no-audio", help="Remove audio from every clip.")
    ] = False,
    fps: Annotated[float | None, typer.Option("--fps", help="Override target fps.")] = None,
    fast: Annotated[
        bool, typer.Option("--fast", help="Stream copy on keyframes. Durations approximate.")
    ] = False,
    rejects: Annotated[
        bool, typer.Option("--rejects", help="Also export rejected segments into _rejects/.")
    ] = False,
    uniform_frame: Annotated[
        bool,
        typer.Option(
            "--uniform-frame",
            help="Put every clip on one frame, the smallest of their sizes. Needed to render.",
        ),
    ] = False,
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Cut, normalize and write the numbered clips into _selects/."""
    cfg = load_config(config, no_cloud)
    manifest = open_project(project)
    # The manifest holds the output folder it was analyzed into; this run may be
    # pointed at a moved copy of that folder, and the clips belong beside it.
    manifest.output_dir = project
    overrides = ExportOverrides(
        no_audio=no_audio,
        fps=fps,
        fast=fast,
        rejects=rejects,
        # None rather than False, so the flag turns the frame on and its absence leaves
        # the decision to autocut.toml.
        uniform_frame=True if uniform_frame else None,
    )

    selected = sum(1 for s in manifest.segments.values() if s.outcome == "selected")
    if selected == 0:
        output.console.print("[red]Nothing selected[/red]. Run autocut select first.")
        raise typer.Exit(code=1)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=output.console,
    ) as progress:
        task = progress.add_task("Exporting", total=selected)

        def on_event(event: ProgressEvent) -> None:
            name = event.path.name if event.path else ""
            progress.update(task, completed=event.current, total=event.total, description=name)

        try:
            result = export_clips(manifest, cfg, on_event, overrides)
        except ToolMissingError as tool_error:
            output.console.print(f"[red]Missing tool[/red]: {tool_error}")
            raise typer.Exit(code=1) from None

    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    report_path = render_report(manifest, project)

    output.console.print(
        f"Exported [bold]{result.exported}[/bold] clips at {result.target_fps:g} fps "
        f"into {result.selects_dir}"
    )
    if result.skipped:
        output.console.print(f"  {result.skipped} unchanged, skipped")
    if result.slow_motion:
        output.console.print(f"  {result.slow_motion} in slow motion")
    if result.fps_converted:
        output.console.print(f"  {result.fps_converted} resampled from another frame rate")
    if result.frame[0] and result.frame[1]:
        output.console.print(f"  every clip on one {result.frame[0]}x{result.frame[1]} frame")
    if result.stale_moved:
        output.console.print(f"  {result.stale_moved} stale files moved to _selects/_stale/")
    for warning in result.warnings:
        output.console.print(f"[yellow]{warning}[/yellow]")
    for segment_id, error in result.errors:
        output.console.print(f"[red]failed[/red] {segment_id}: {error}")
    output.console.print(f"Report written to {report_path}")
    # The same switch the Export screen's toggle writes, so a project configured in the
    # window behaves the same way from the command line.
    if cfg.render.enabled and not result.failed:
        rendered = render_edit(manifest, cfg)
        manifest.save(project / "manifest.json")
        output.print_render(rendered)
        render_report(manifest, project)
    if result.failed:
        raise typer.Exit(code=1)

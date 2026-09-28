"""The ``run`` command: the first pass shortcut chaining analyze, select, report."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from autocut.cli.commands.analyze import analyze
from autocut.cli.commands.report import report
from autocut.cli.commands.select import select
from autocut.cli.commands.soundtrack import soundtrack
from autocut.cli.common import ConfigOpt, NoCloudOpt


def run(
    sources: Annotated[list[Path], typer.Argument()],
    out: Annotated[Path, typer.Option("--out", "-o")],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
    no_proxies: Annotated[
        bool, typer.Option("--no-proxies", help="Ignore .lrv and .lrf proxy files.")
    ] = False,
    workers: Annotated[
        int | None, typer.Option("--workers", help="Parallel files. Defaults to physical cores.")
    ] = None,
    max_clips: Annotated[int | None, typer.Option("--max-clips")] = None,
    duration: Annotated[float | None, typer.Option("--duration", help="Target seconds.")] = None,
    diversity: Annotated[float | None, typer.Option("--diversity", help="Lambda, 0 to 1.")] = None,
) -> None:
    """First pass shortcut: analyze, then select, then report."""
    # Typer's decorator returns the function unchanged, so these are plain calls and
    # each command's typer.Exit propagates with its own status.
    analyze(
        sources=sources,
        out=out,
        config=config,
        no_cloud=no_cloud,
        no_proxies=no_proxies,
        workers=workers,
    )
    select(
        project=out,
        max_clips=max_clips,
        duration=duration,
        diversity=diversity,
        config=config,
    )
    soundtrack(project=out, config=config, no_cloud=no_cloud)
    report(project=out, config=config)

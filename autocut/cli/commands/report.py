"""The ``report`` command: report.html for visual review."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from autocut.cli import output
from autocut.cli.common import ConfigOpt, NoCloudOpt, load_config, load_manifest
from autocut.core.report import render_report


def report(
    project: Annotated[Path, typer.Argument()],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Write report.html for visual review."""
    load_config(config, no_cloud)
    manifest_path = project / "manifest.json"
    if not manifest_path.exists():
        output.console.print(f"[red]No manifest found[/red] at {manifest_path}. Run analyze first.")
        raise typer.Exit(code=1)
    path = render_report(load_manifest(manifest_path), project)
    output.console.print(f"Report written to {path}")

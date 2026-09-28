"""The ``doctor`` command: what this machine provides."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from autocut.cli import output
from autocut.cli.common import ConfigOpt, NoCloudOpt, load_config
from autocut.core.doctor import inspect_environment


def doctor(
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the same facts as a JSON object.")
    ] = False,
    sample: Annotated[
        Path | None,
        typer.Option("--sample", help="Video file to verify the hardware decoder against."),
    ] = None,
) -> None:
    """Report what this machine provides: binaries, decoder, extra, model, key, cache."""
    report = inspect_environment(load_config(config, no_cloud), sample)
    if as_json:
        # Written straight to stdout: Rich would soft wrap a long cache path and the
        # output has to parse.
        typer.echo(json.dumps(report.as_dict(), indent=2))
    else:
        for check in report.checks:
            colour = "green" if check.ok else "yellow"
            output.console.print(
                f"[{colour}]{check.marker:>7}[/{colour}] {check.name}: {check.detail}"
            )
    if not report.ok:
        raise typer.Exit(code=1)

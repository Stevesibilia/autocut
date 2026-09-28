"""The ``cache`` sub-app: inspect and prune the global analysis cache. See ADR 6."""

from __future__ import annotations

from typing import Annotated

import typer

from autocut.cli import output
from autocut.cli.common import ConfigOpt, load_config
from autocut.core.cache import cache_stats, prune

cache_app = typer.Typer(
    name="cache",
    help="Inspect and prune the global analysis cache. See ADR 6.",
    invoke_without_command=True,
)


@cache_app.callback(invoke_without_command=True)
def cache_root(ctx: typer.Context, config: ConfigOpt = None) -> None:
    """Report the cache directory, entry count and total size."""
    if ctx.invoked_subcommand is not None:
        return
    stats = cache_stats(load_config(config))
    output.console.print(f"Cache directory: {stats.directory}")
    output.console.print(f"Entries: [bold]{stats.entries}[/bold]")
    output.console.print(f"Size: [bold]{stats.megabytes:.1f}[/bold] MB")


@cache_app.command("prune")
def cache_prune(
    older_than: Annotated[
        float, typer.Option("--older-than", help="Delete entries older than this many days.")
    ] = 90.0,
    config: ConfigOpt = None,
) -> None:
    """Delete cache entries that have not been touched for a while."""
    removed = prune(load_config(config), older_than)
    output.console.print(f"Removed [bold]{removed}[/bold] entries older than {older_than:g} days.")

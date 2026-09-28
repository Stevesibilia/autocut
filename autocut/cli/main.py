"""AutoCut command line interface.

Every command lives in its own module under ``autocut/cli/commands/``; this module
only builds the ``Typer`` app and registers each command and sub-app under the name it
has always had. The entry point in ``pyproject.toml`` points at ``app`` here.
"""

from __future__ import annotations

from typing import Annotated

import typer

from autocut import __version__
from autocut.cli import output
from autocut.cli.commands.analyze import analyze
from autocut.cli.commands.cache import cache_app
from autocut.cli.commands.doctor import doctor
from autocut.cli.commands.enrich import describe, embed, tag
from autocut.cli.commands.export import export
from autocut.cli.commands.gui import gui
from autocut.cli.commands.keys import key_app
from autocut.cli.commands.render import render
from autocut.cli.commands.report import report
from autocut.cli.commands.run import run
from autocut.cli.commands.select import select
from autocut.cli.commands.soundtrack import soundtrack
from autocut.cli.commands.sync import sync

app = typer.Typer(
    name="autocut",
    help="Select, trim, order and normalize vacation footage clips for CapCut.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    if version:
        output.console.print(__version__, highlight=False)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        output.console.print(ctx.get_help())
        raise typer.Exit()


app.command()(analyze)
app.command()(embed)
app.command()(tag)
app.command()(describe)
app.command()(doctor)
app.command()(select)
app.command()(soundtrack)
app.command()(report)
app.command()(sync)
app.command()(export)
app.command()(render)
app.command()(gui)
app.command()(run)
app.add_typer(key_app)
app.add_typer(cache_app)


if __name__ == "__main__":
    app()

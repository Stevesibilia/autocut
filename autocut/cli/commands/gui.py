"""The ``gui`` command: open the desktop window."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from autocut.cli import output


def gui(
    project: Annotated[
        Path | None,
        typer.Argument(help="Project folder to open on start. Optional."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Log every playback and layout step to the terminal, for a bug report.",
        ),
    ] = False,
    diagnose: Annotated[
        bool,
        typer.Option(
            "--diagnose",
            help="Print the screens, fonts, theme and window sizes this machine reports, "
            "then exit without opening a window.",
        ),
    ] = False,
) -> None:
    """Open the desktop window. Needs the gui extra."""
    try:
        from autocut.gui.app import run as run_gui
    except ImportError as error:
        output.console.print(
            "[red]The gui extra is not installed.[/red] Install it with: "
            # Escaped, because the one part of this line the user has to type
            # verbatim is the part Rich would read as markup and eat.
            r'pip install -e ".\[gui]"'
        )
        output.console.print(f"  {error}")
        raise typer.Exit(code=1) from error
    if diagnose:
        # Imported here rather than beside `run`: a failure to import the report is not
        # a missing gui extra, and pulling it in unconditionally made every caller
        # depend on it.
        from autocut.gui.app import diagnose as diagnose_gui

        raise typer.Exit(code=diagnose_gui())
    raise typer.Exit(code=run_gui(project, verbose=verbose))

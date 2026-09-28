"""The ``key`` sub-app: storing and clearing the provider API key."""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from autocut.cli import output
from autocut.core.providers import clear_key, set_key

key_app = typer.Typer(name="key", help="Store the provider API key in the OS keychain.")


@key_app.command("set")
def key_set(
    from_stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read the key from standard input, for a script or a pipe."),
    ] = False,
) -> None:
    """Store an OpenRouter key in the keychain. It never goes into autocut.toml.

    There is deliberately no option to pass the key as an argument. An argument is
    visible in ``ps`` and in ``/proc/*/cmdline`` to every other user on the machine, and
    it lands in the shell history. Interactively the key is prompted for without echo;
    a script pipes it in with ``--stdin``.
    """
    secret = sys.stdin.readline() if from_stdin else typer.prompt("OpenRouter key", hide_input=True)
    if not secret.strip():
        output.console.print("[red]No key given[/red]; nothing was stored.")
        raise typer.Exit(code=2)
    try:
        set_key(secret.strip())
    except Exception as exc:  # noqa: BLE001 - any keyring backend failure reads the same
        output.console.print(f"[red]Could not store the key[/red]: {exc}")
        raise typer.Exit(code=1) from exc
    output.console.print("Key stored in the keychain as autocut/openrouter.")


@key_app.command("clear")
def key_clear() -> None:
    """Remove the stored key. The environment variable, if set, still wins."""
    if clear_key():
        output.console.print("Key removed from the keychain.")
    else:
        output.console.print("No key was stored in the keychain.")

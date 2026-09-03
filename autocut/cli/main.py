"""AutoCut command line interface.

Each command reads and writes the same ``manifest.json`` and can be re-run on
its own. Command bodies are filled in milestone by milestone; until then they
report that the stage is not implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from autocut import __version__
from autocut.core.config import AutocutConfig

app = typer.Typer(
    name="autocut",
    help="Select, trim, order and normalize vacation footage clips for CapCut.",
    no_args_is_help=True,
)
console = Console()

ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to autocut.toml. Defaults to ./autocut.toml."),
]


def _load_config(path: Path | None) -> AutocutConfig:
    return AutocutConfig.load(path or Path("autocut.toml"))


def _not_implemented(stage: str) -> None:
    console.print(f"[yellow]{stage}[/yellow] is not implemented yet. See SPEC.md section 15.")
    raise typer.Exit(code=2)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def analyze(
    sources: Annotated[list[Path], typer.Argument(help="Source folders to scan.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output folder.")],
    config: ConfigOpt = None,
    no_cloud: Annotated[bool, typer.Option("--no-cloud", help="Disable cloud providers.")] = False,
) -> None:
    """Scan, probe and analyze footage. Writes manifest.json and report.html."""
    _load_config(config)
    _not_implemented("analyze")


@app.command()
def select(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    max_clips: Annotated[int | None, typer.Option("--max-clips")] = None,
    duration: Annotated[float | None, typer.Option("--duration", help="Target seconds.")] = None,
    diversity: Annotated[float | None, typer.Option("--diversity", help="Lambda, 0 to 1.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Pick the best window per segment and the final diverse set of clips."""
    _load_config(config)
    _not_implemented("select")


@app.command()
def soundtrack(
    project: Annotated[Path, typer.Argument()],
    variants: Annotated[int | None, typer.Option("--variants")] = None,
    config: ConfigOpt = None,
) -> None:
    """Generate the music prompt from the selected clips."""
    _load_config(config)
    _not_implemented("soundtrack")


@app.command()
def report(project: Annotated[Path, typer.Argument()], config: ConfigOpt = None) -> None:
    """Write report.html for visual review."""
    _load_config(config)
    _not_implemented("report")


@app.command()
def sync(
    project: Annotated[Path, typer.Argument()],
    audio: Annotated[Path, typer.Option("--audio", help="Generated track.")],
    bpm: Annotated[float | None, typer.Option("--bpm", help="Override measured BPM.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Measure the track BPM and quantize clip durations to beats."""
    _load_config(config)
    _not_implemented("sync")


@app.command()
def export(
    project: Annotated[Path, typer.Argument()],
    no_audio: Annotated[bool, typer.Option("--no-audio")] = False,
    fps: Annotated[float | None, typer.Option("--fps", help="Override target fps.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Cut, normalize and write the numbered clips into _selects/."""
    _load_config(config)
    _not_implemented("export")


@app.command()
def run(
    sources: Annotated[list[Path], typer.Argument()],
    out: Annotated[Path, typer.Option("--out", "-o")],
    config: ConfigOpt = None,
) -> None:
    """First pass shortcut: analyze, select, soundtrack, report."""
    _load_config(config)
    _not_implemented("run")


if __name__ == "__main__":
    app()

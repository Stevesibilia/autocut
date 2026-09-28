"""The ``soundtrack`` command: the Suno prompt from the selected clips."""

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
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressEvent
from autocut.core.providers import cloud_enabled, find_key
from autocut.core.providers.openrouter import OpenRouterProvider
from autocut.core.soundtrack.build import build_soundtrack


def soundtrack(
    project: Annotated[Path, typer.Argument()],
    variants: Annotated[
        int | None, typer.Option("--variants", help="How many prompts to write, 1 to 5.")
    ] = None,
    bpm: Annotated[
        int | None, typer.Option("--bpm", help="Force the BPM instead of fitting one.")
    ] = None,
    genre: Annotated[
        str | None, typer.Option("--genre", help="Force a row from the genre table by name.")
    ] = None,
    no_geocode: Annotated[
        bool, typer.Option("--no-geocode", help="Skip naming the places, staying offline.")
    ] = False,
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Write the Suno prompt from the selected clips into suno-prompt.md."""
    cfg = load_config(config, no_cloud)
    manifest = open_project(project)
    manifest.output_dir = project

    provider, reason = _text_provider(cfg, no_cloud)
    try:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=output.console,
        ) as bar:
            task = bar.add_task("Soundtrack", total=None)

            def on_event(event: ProgressEvent) -> None:
                bar.update(
                    task,
                    completed=event.current,
                    total=event.total,
                    description=event.stage.title(),
                )

            try:
                result = build_soundtrack(
                    manifest,
                    cfg,
                    provider,
                    on_event,
                    bpm_override=bpm,
                    genre_override=genre,
                    variants=variants,
                    geocode=not no_geocode,
                    refine_note=reason,
                )
            except ValueError as exc:
                output.console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=2) from exc
    finally:
        if provider is not None:
            provider.close()

    if result.skipped:
        output.console.print(f"[red]{result.skipped_reason}[/red]")
        raise typer.Exit(code=1)

    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    output.print_soundtrack(result, reason)


def _text_provider(cfg: AutocutConfig, no_cloud: bool) -> tuple[OpenRouterProvider | None, str]:
    """The text provider for refinement, or ``None`` and the reason there is none."""
    if not cfg.soundtrack.refine:
        return None, "soundtrack.refine is false"
    enabled, reason = cloud_enabled(cfg, no_cloud)
    if not enabled:
        return None, reason
    key = find_key()
    assert key is not None
    return OpenRouterProvider(key, cfg), reason

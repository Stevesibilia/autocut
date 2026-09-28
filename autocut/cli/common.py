"""Option types and manifest/config helpers shared by every command."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import pydantic
import typer

from autocut.cli import output
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest

ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to autocut.toml. Defaults to ./autocut.toml."),
]

# On every command, because a user scripting the pipeline should be able to put it on
# any of them and get a run that reaches no provider. On the commands that make no
# provider call it simply has nothing to switch off.
NoCloudOpt = Annotated[
    bool, typer.Option("--no-cloud", help="Make no call to a hosted provider in this run.")
]


def _one_line(error: Exception) -> str:
    """The first line of an error's message, so a multi-line pydantic report stays one line."""
    text = str(error).strip()
    first = text.splitlines()[0] if text else ""
    if isinstance(error, pydantic.ValidationError):
        return f"{first} ({error.error_count()} error{'s' if error.error_count() != 1 else ''})"
    return first


def load_config(path: Path | None, no_cloud: bool = False) -> AutocutConfig:
    """The configuration for this run, with ``--no-cloud`` applied.

    The flag is applied here rather than at each call site so it means the same thing
    everywhere: this run reaches no provider. On a command that makes no provider call
    it still has an effect worth having, since ``doctor`` then reports the run as it is.

    An explicit ``--config`` path that does not exist is refused: a typo should not
    silently fall back to defaults. No ``--config`` and no ``autocut.toml`` in the
    working directory is not an error, and keeps loading the defaults as before.
    """
    resolved = path or Path("autocut.toml")
    if path is not None and not resolved.exists():
        output.console.print(f"[red]Configuration not found[/red]: {resolved}")
        raise typer.Exit(code=1)
    try:
        config = AutocutConfig.load(resolved)
    except (OSError, tomllib.TOMLDecodeError, pydantic.ValidationError) as error:
        output.console.print(
            f"[red]Cannot read the configuration[/red] {resolved}: {_one_line(error)}"
        )
        raise typer.Exit(code=1) from None
    if no_cloud:
        config.providers.cloud = False
    return config


def load_manifest(path: Path) -> Manifest:
    """Load a manifest, reporting an unreadable file as one line instead of a traceback.

    ``ManifestVersionError``, ``json.JSONDecodeError`` and ``pydantic.ValidationError``
    are all ``ValueError``, so one guard covers a refused newer schema, invalid JSON and
    a manifest that fails validation alike.
    """
    try:
        return Manifest.load(path)
    except (OSError, ValueError) as error:
        output.console.print(f"[red]Cannot open the project[/red]: {_one_line(error)}")
        raise typer.Exit(code=1) from None


def open_manifest(out: Path, sources: list[Path], cfg: AutocutConfig) -> Manifest:
    """Load the manifest in ``out`` when it exists, otherwise start a new one."""
    path = out / "manifest.json"
    now = datetime.now(UTC)
    resolved = [source.resolve() for source in sources]
    if path.exists():
        manifest = load_manifest(path)
        manifest.sources = resolved
        manifest.output_dir = out
        manifest.config_snapshot = cfg.model_dump(mode="json")
        return manifest
    return Manifest(
        created_at=now,
        updated_at=now,
        sources=resolved,
        output_dir=out,
        config_snapshot=cfg.model_dump(mode="json"),
    )


def open_project(project: Path) -> Manifest:
    """Load the manifest of an analyzed project, or exit with a clear message."""
    manifest_path = project / "manifest.json"
    if not manifest_path.exists():
        output.console.print(f"[red]No manifest found[/red] at {manifest_path}. Run analyze first.")
        raise typer.Exit(code=1)
    return load_manifest(manifest_path)

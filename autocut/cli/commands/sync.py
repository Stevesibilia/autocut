"""The ``sync`` command: measure the track BPM and quantize clip durations to beats."""

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
from autocut.core.beatsync import (
    AudioUnavailableError,
    compare_bpm,
    decode_audio,
    measure_track,
    quantize_durations,
    record_sync,
    reset_final_bounds,
    write_beatmap,
)
from autocut.core.events import ProgressEvent


def sync(
    project: Annotated[Path, typer.Argument()],
    audio: Annotated[Path, typer.Option("--audio", help="Generated track.")],
    bpm: Annotated[float | None, typer.Option("--bpm", help="Override measured BPM.")] = None,
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Measure the track BPM and quantize clip durations to beats."""
    cfg = load_config(config, no_cloud)
    manifest = open_project(project)
    manifest.output_dir = project

    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    if not selected:
        output.console.print("[red]Nothing selected[/red]. Run autocut select first.")
        raise typer.Exit(code=1)
    if not audio.exists():
        output.console.print(f"[red]No such track[/red]: {audio}")
        raise typer.Exit(code=1)

    # A re-run is a fresh measurement, not a drift on top of the last one.
    reset_final_bounds(manifest)
    try:
        track = measure_track(decode_audio(audio, timeout_s=cfg.timeouts.audio_decode_s))
    except AudioUnavailableError as exc:
        output.console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    effective = bpm if bpm is not None else track.bpm
    comparison = compare_bpm(
        manifest.soundtrack.proposed_bpm, effective, cfg.soundtrack.bpm_tolerance
    )

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=output.console,
    ) as bar:
        task = bar.add_task("Quantizing", total=len(selected))

        def on_event(event: ProgressEvent) -> None:
            bar.update(task, completed=event.current, total=event.total)

        result = quantize_durations(manifest, effective, cfg, on_event)

    manifest.soundtrack.audio_path = audio
    manifest.soundtrack.measured_bpm = track.bpm
    manifest.soundtrack.bpm_override = bpm
    manifest.soundtrack.beats_s = track.beats_s
    manifest.soundtrack.comparison = comparison.status
    manifest.soundtrack.comparison_note = comparison.note
    beatmap = write_beatmap(manifest, track, project)
    manifest.soundtrack.beatmap_path = beatmap
    record_sync(manifest, effective, audio)
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")

    output.print_sync(track, effective, comparison, result, beatmap, override=bpm is not None)

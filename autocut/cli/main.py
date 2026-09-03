"""AutoCut command line interface.

Each command reads and writes the same ``manifest.json`` and can be re-run on
its own. Command bodies are filled in milestone by milestone; until then they
report that the stage is not implemented.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

from autocut import __version__
from autocut.core.analyze import AnalysisCancelled, analyze_files
from autocut.core.cache import cache_stats, prune
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressEvent
from autocut.core.export import export_clips
from autocut.core.ffmpeg_cmd import ExportOverrides
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest
from autocut.core.report import render_report
from autocut.core.select import SelectionOverrides, select_clips

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
        console.print(__version__, highlight=False)
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
    no_proxies: Annotated[
        bool, typer.Option("--no-proxies", help="Ignore .lrv and .lrf proxy files.")
    ] = False,
    workers: Annotated[
        int | None, typer.Option("--workers", help="Parallel files. Defaults to physical cores.")
    ] = None,
) -> None:
    """Scan, probe and analyze footage. Writes manifest.json and report.html."""
    cfg = _load_config(config)
    if no_cloud:
        cfg.providers.cloud = False
    if no_proxies:
        cfg.analysis.use_proxies = False
    if workers is not None:
        cfg.analysis.workers = workers

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Probing", total=None)

        def on_event(event: ProgressEvent) -> None:
            if event.stage == "scan":
                progress.update(task, total=event.total or None)
                return
            name = event.path.name if event.path else ""
            progress.update(task, completed=event.current, total=event.total, description=name)

        files = ingest(list(sources), cfg, on_event)

    if not files:
        console.print("[red]No video files found[/red] in the given source folders.")
        raise typer.Exit(code=1)

    manifest_path = out / "manifest.json"
    manifest = _open_manifest(out, sources, cfg)
    manifest.files = {source.id: source for source in files}
    manifest.updated_at = datetime.now(UTC)
    # Saved once here so an interrupted analysis still leaves a usable file list.
    manifest.save(manifest_path)

    failed = [source for source in files if source.error]
    console.print(f"Probed [bold]{len(files)}[/bold] files into {manifest_path}")
    for source in failed:
        console.print(f"[yellow]unreadable[/yellow] {source.path}: {source.error}")

    cached = 0
    interrupted = False
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing", total=len(files) - len(failed))

        def on_analysis(event: ProgressEvent) -> None:
            nonlocal cached
            if event.extra.get("cached"):
                cached += 1
            name = event.path.name if event.path else ""
            suffix = " (cached)" if event.extra.get("cached") else ""
            progress.update(
                task, completed=event.current, total=event.total, description=f"{name}{suffix}"
            )

        try:
            analyze_files(manifest, cfg, on_analysis)
        except AnalysisCancelled:
            interrupted = True

    manifest.updated_at = datetime.now(UTC)
    manifest.save(manifest_path)

    report_path = render_report(manifest, out)

    for warning in manifest.analysis.warnings:
        console.print(f"[yellow]{warning}[/yellow]")

    rejected = Counter(s.reason for s in manifest.segments.values() if s.reason)
    console.print(
        f"Analyzed [bold]{len(manifest.segments)}[/bold] segments "
        f"({cached} files from cache), {sum(rejected.values())} rejected"
    )
    for reason, count in sorted(rejected.items()):
        console.print(f"  {reason}: {count}")
    console.print(f"Report written to {report_path}")
    if interrupted:
        console.print(
            "[yellow]Analysis was cancelled[/yellow]; the manifest holds partial results."
        )
        raise typer.Exit(code=130)


def _open_manifest(out: Path, sources: list[Path], cfg: AutocutConfig) -> Manifest:
    """Load the manifest in ``out`` when it exists, otherwise start a new one."""
    path = out / "manifest.json"
    now = datetime.now(UTC)
    resolved = [source.resolve() for source in sources]
    if path.exists():
        manifest = Manifest.load(path)
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


def _open_project(project: Path) -> Manifest:
    """Load the manifest of an analyzed project, or exit with a clear message."""
    manifest_path = project / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]No manifest found[/red] at {manifest_path}. Run analyze first.")
        raise typer.Exit(code=1)
    return Manifest.load(manifest_path)


@app.command()
def select(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    max_clips: Annotated[int | None, typer.Option("--max-clips")] = None,
    duration: Annotated[
        float | None,
        typer.Option("--duration", help="One length for every clip, instead of varied lengths."),
    ] = None,
    diversity: Annotated[float | None, typer.Option("--diversity", help="Lambda, 0 to 1.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Pick the best window per segment and the final diverse set of clips."""
    cfg = _load_config(config)
    manifest = _open_project(project)
    result = select_clips(
        manifest,
        cfg,
        SelectionOverrides(
            max_clips=max_clips, target_duration_s=duration, diversity_lambda=diversity
        ),
    )
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")

    per_class = Counter(
        manifest.files[s.file_id].source_class
        for s in manifest.segments.values()
        if s.outcome == "selected" and s.file_id in manifest.files
    )
    console.print(
        f"Selected [bold]{result.count}[/bold] of {result.max_clips} clips "
        f"from {result.clusters} clusters, diversity {result.diversity_lambda:g}"
    )
    console.print(f"  {result.places} places, {result.visits} visits")
    if result.held_by_place:
        console.print(
            f"  {result.held_by_place} candidates held back by the place cap "
            f"of {cfg.selection.max_clips_per_place} per visit"
        )
    if result.ceiling_applied:
        console.print(
            f"[yellow]The candidate share ceiling applied[/yellow]: at most "
            f"{cfg.selection.max_candidate_share:g} of the eligible candidates, so "
            f"{result.max_clips} slots. Pass --max-clips to override it."
        )
    for name, count in sorted(per_class.items()):
        console.print(f"  {name}: {count}")
    if result.varied_durations:
        console.print(
            f"Total [bold]{result.total_duration_s:.1f} s[/bold]: "
            f"{result.long_clips} long, {result.short_clips} short, {result.hero_clips} hero"
        )
    else:
        console.print(
            f"Total [bold]{result.total_duration_s:.1f} s[/bold], one length for every clip"
        )
    if abs(result.total_shortfall_s) > 0.05:
        console.print(
            f"[yellow]The total target was missed by {result.total_shortfall_s:+.1f} s[/yellow]; "
            "the duration bounds were reached first."
        )
    snapped = sum(1 for s in manifest.segments.values() if s.outcome == "selected" and s.snapped)
    if snapped:
        console.print(f"  {snapped} windows moved onto a motion boundary")
    if result.relaxed_gap:
        console.print(
            "[yellow]The minimum temporal gap was relaxed[/yellow] to fill the remaining slots."
        )


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
    manifest_path = project / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]No manifest found[/red] at {manifest_path}. Run analyze first.")
        raise typer.Exit(code=1)
    path = render_report(Manifest.load(manifest_path), project)
    console.print(f"Report written to {path}")


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
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    no_audio: Annotated[
        bool, typer.Option("--no-audio", help="Remove audio from every clip.")
    ] = False,
    fps: Annotated[float | None, typer.Option("--fps", help="Override target fps.")] = None,
    fast: Annotated[
        bool, typer.Option("--fast", help="Stream copy on keyframes. Durations approximate.")
    ] = False,
    rejects: Annotated[
        bool, typer.Option("--rejects", help="Also export rejected segments into _rejects/.")
    ] = False,
    config: ConfigOpt = None,
) -> None:
    """Cut, normalize and write the numbered clips into _selects/."""
    cfg = _load_config(config)
    manifest = _open_project(project)
    # The manifest holds the output folder it was analyzed into; this run may be
    # pointed at a moved copy of that folder, and the clips belong beside it.
    manifest.output_dir = project
    overrides = ExportOverrides(no_audio=no_audio, fps=fps, fast=fast, rejects=rejects)

    selected = sum(1 for s in manifest.segments.values() if s.outcome == "selected")
    if selected == 0:
        console.print("[red]Nothing selected[/red]. Run autocut select first.")
        raise typer.Exit(code=1)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Exporting", total=selected)

        def on_event(event: ProgressEvent) -> None:
            name = event.path.name if event.path else ""
            progress.update(task, completed=event.current, total=event.total, description=name)

        result = export_clips(manifest, cfg, on_event, overrides)

    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    report_path = render_report(manifest, project)

    console.print(
        f"Exported [bold]{result.exported}[/bold] clips at {result.target_fps:g} fps "
        f"into {result.selects_dir}"
    )
    if result.skipped:
        console.print(f"  {result.skipped} unchanged, skipped")
    if result.slow_motion:
        console.print(f"  {result.slow_motion} in slow motion")
    if result.fps_converted:
        console.print(f"  {result.fps_converted} resampled from another frame rate")
    if result.stale_moved:
        console.print(f"  {result.stale_moved} stale files moved to _selects/_stale/")
    for warning in result.warnings:
        console.print(f"[yellow]{warning}[/yellow]")
    for segment_id, error in result.errors:
        console.print(f"[red]failed[/red] {segment_id}: {error}")
    console.print(f"Report written to {report_path}")
    if result.failed:
        raise typer.Exit(code=1)


@app.command()
def run(
    sources: Annotated[list[Path], typer.Argument()],
    out: Annotated[Path, typer.Option("--out", "-o")],
    config: ConfigOpt = None,
    no_cloud: Annotated[bool, typer.Option("--no-cloud", help="Disable cloud providers.")] = False,
    no_proxies: Annotated[
        bool, typer.Option("--no-proxies", help="Ignore .lrv and .lrf proxy files.")
    ] = False,
    workers: Annotated[
        int | None, typer.Option("--workers", help="Parallel files. Defaults to physical cores.")
    ] = None,
    max_clips: Annotated[int | None, typer.Option("--max-clips")] = None,
    duration: Annotated[float | None, typer.Option("--duration", help="Target seconds.")] = None,
    diversity: Annotated[float | None, typer.Option("--diversity", help="Lambda, 0 to 1.")] = None,
) -> None:
    """First pass shortcut: analyze, then select, then report."""
    # Typer's decorator returns the function unchanged, so these are plain calls and
    # each command's typer.Exit propagates with its own status.
    analyze(
        sources=sources,
        out=out,
        config=config,
        no_cloud=no_cloud,
        no_proxies=no_proxies,
        workers=workers,
    )
    select(
        project=out,
        max_clips=max_clips,
        duration=duration,
        diversity=diversity,
        config=config,
    )
    report(project=out, config=config)


cache_app = typer.Typer(
    name="cache",
    help="Inspect and prune the global analysis cache. See ADR 6.",
    invoke_without_command=True,
)
app.add_typer(cache_app)


@cache_app.callback(invoke_without_command=True)
def cache_root(ctx: typer.Context, config: ConfigOpt = None) -> None:
    """Report the cache directory, entry count and total size."""
    if ctx.invoked_subcommand is not None:
        return
    stats = cache_stats(_load_config(config))
    console.print(f"Cache directory: {stats.directory}")
    console.print(f"Entries: [bold]{stats.entries}[/bold]")
    console.print(f"Size: [bold]{stats.megabytes:.1f}[/bold] MB")


@cache_app.command("prune")
def cache_prune(
    older_than: Annotated[
        float, typer.Option("--older-than", help="Delete entries older than this many days.")
    ] = 90.0,
    config: ConfigOpt = None,
) -> None:
    """Delete cache entries that have not been touched for a while."""
    removed = prune(_load_config(config), older_than)
    console.print(f"Removed [bold]{removed}[/bold] entries older than {older_than:g} days.")


if __name__ == "__main__":
    app()

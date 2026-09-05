"""AutoCut command line interface.

Each command reads and writes the same ``manifest.json`` and can be re-run on
its own. Command bodies are filled in milestone by milestone; until then they
report that the stage is not implemented.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from autocut import __version__
from autocut.core.analyze import AnalysisCancelled, analyze_files
from autocut.core.beatsync import (
    AudioUnavailableError,
    QuantizeResult,
    Track,
    compare_bpm,
    decode_audio,
    measure_track,
    quantize_durations,
    record_sync,
    reset_final_bounds,
    write_beatmap,
)
from autocut.core.cache import cache_stats, prune
from autocut.core.config import AutocutConfig
from autocut.core.describe import DescribeResult, describe_project
from autocut.core.doctor import inspect_environment
from autocut.core.embeddings import EmbedResult, embed_project
from autocut.core.events import ProgressEvent
from autocut.core.export import export_clips
from autocut.core.ffmpeg_cmd import ExportOverrides
from autocut.core.ingest import ingest
from autocut.core.manifest import Manifest
from autocut.core.providers import clear_key, cloud_enabled, find_key, set_key
from autocut.core.providers.openrouter import OpenRouterProvider
from autocut.core.report import render_report
from autocut.core.select import SelectionOverrides, select_clips
from autocut.core.soundtrack.build import SoundtrackResult, build_soundtrack
from autocut.core.tags import TagResult, tag_project

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

# On every command, because a user scripting the pipeline should be able to put it on
# any of them and get a run that reaches no provider. On the commands that make no
# provider call it simply has nothing to switch off.
NoCloudOpt = Annotated[
    bool, typer.Option("--no-cloud", help="Make no call to a hosted provider in this run.")
]


def _load_config(path: Path | None, no_cloud: bool = False) -> AutocutConfig:
    """The configuration for this run, with ``--no-cloud`` applied.

    The flag is applied here rather than at each call site so it means the same thing
    everywhere: this run reaches no provider. On a command that makes no provider call
    it still has an effect worth having, since ``doctor`` then reports the run as it is.
    """
    config = AutocutConfig.load(path or Path("autocut.toml"))
    if no_cloud:
        config.providers.cloud = False
    return config


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
    no_cloud: NoCloudOpt = False,
    no_proxies: Annotated[
        bool, typer.Option("--no-proxies", help="Ignore .lrv and .lrf proxy files.")
    ] = False,
    workers: Annotated[
        int | None, typer.Option("--workers", help="Parallel files. Defaults to physical cores.")
    ] = None,
) -> None:
    """Scan, probe and analyze footage. Writes manifest.json and report.html."""
    cfg = _load_config(config, no_cloud)
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

    embedded = _run_embed(manifest, cfg)
    tagged = _run_tag(manifest, cfg)
    described = _run_describe(manifest, cfg, no_cloud)
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
    _print_embed(embedded)
    _print_tag(tagged)
    _print_describe(described)
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


def _run_embed(manifest: Manifest, cfg: AutocutConfig) -> EmbedResult:
    """Embed the project and record on the run what did it and where.

    The progress bar is built on the first event rather than up front, so a project
    that is already embedded, or a machine without the extra, prints one line and no
    empty bar.
    """
    bar: Progress | None = None
    task: TaskID | None = None

    def on_event(event: ProgressEvent) -> None:
        nonlocal bar, task
        if bar is None:
            bar = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            )
            bar.start()
            task = bar.add_task("Embedding", total=event.total)
        assert task is not None
        bar.update(task, completed=event.current, total=event.total)

    try:
        result = embed_project(manifest, cfg, on_event)
    finally:
        if bar is not None:
            bar.stop()
    manifest.analysis.embedding_model = result.model
    manifest.analysis.embedding_device = result.device
    return result


def _print_embed(result: EmbedResult) -> None:
    if result.skipped_reason is not None:
        console.print(f"Embeddings skipped: {result.skipped_reason}")
        return
    console.print(
        f"Embedded [bold]{result.segments}[/bold] segments with {result.model} "
        f"on {result.device} ({result.files_embedded} files computed, "
        f"{result.files_from_cache} from cache)"
    )
    for warning in result.warnings:
        console.print(f"[yellow]{warning}[/yellow]")


@app.command()
def embed(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Compute the missing segment embeddings from the analysis cache."""
    cfg = _load_config(config, no_cloud)
    manifest = _open_project(project)
    result = _run_embed(manifest, cfg)
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    _print_embed(result)


def _run_tag(manifest: Manifest, cfg: AutocutConfig) -> TagResult:
    """Recompute the local tags. Cheap enough that no progress bar is worth the noise."""
    return tag_project(manifest, cfg)


def _print_tag(result: TagResult) -> None:
    if result.skipped_reason is not None:
        console.print(f"Tagging skipped: {result.skipped_reason}")
        return
    console.print(
        f"Tagged [bold]{result.with_a_tag}[/bold] of {result.embedded} embedded segments "
        f"against {result.labels} labels in {result.groups} groups"
    )
    console.print(
        f"  {result.with_a_subject} carry a subject and are named after it, "
        f"{result.embedded - result.with_a_subject} fall back to clip"
    )
    if result.without_an_embedding:
        console.print(f"  {result.without_an_embedding} without an embedding, left untagged")
    for group, labels in result.per_group.items():
        listed = ", ".join(f"{label} {count}" for label, count in labels.items())
        console.print(f"  {group}: {listed}")


@app.command()
def tag(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Recompute the semantic tags from the cached embeddings and the label set."""
    cfg = _load_config(config, no_cloud)
    manifest = _open_project(project)
    result = _run_tag(manifest, cfg)
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    _print_tag(result)


def _run_describe(manifest: Manifest, cfg: AutocutConfig, no_cloud: bool) -> DescribeResult:
    """Describe the project through the configured provider, or say why it did not.

    Cloud needs three things to agree and this is where the answer is recorded on the
    run, so a manifest says whether a hosted model saw the footage and what it cost.
    """
    enabled, reason = cloud_enabled(cfg, no_cloud)
    if not enabled:
        result = DescribeResult(scope=cfg.providers.describe_scope, skipped_reason=reason)
    else:
        key = find_key()
        # cloud_enabled already established there is one; this keeps the type honest.
        assert key is not None
        with (
            OpenRouterProvider(key, cfg) as provider,
            Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as bar,
        ):
            task = bar.add_task("Describing", total=None)

            def on_event(event: ProgressEvent) -> None:
                bar.update(task, completed=event.current, total=event.total)

            result = describe_project(manifest, cfg, provider, on_event)

    manifest.analysis.cloud_model = "none" if result.skipped else result.model
    manifest.analysis.cloud_requests = result.requests
    manifest.analysis.cloud_cost_usd = result.cost_usd
    return result


def _print_describe(result: DescribeResult) -> None:
    if result.skipped_reason is not None:
        console.print(f"Descriptions skipped: {result.skipped_reason}")
        return
    console.print(
        f"Described [bold]{result.described}[/bold] of {result.in_scope} segments "
        f"in scope ({result.scope}) with {result.model}"
    )
    console.print(
        f"  {result.requests} requests, {result.from_cache} from cache, "
        f"[bold]{result.cost_usd:.4f} USD[/bold]"
    )
    if result.aborted:
        console.print("[yellow]Describing stopped early[/yellow] after repeated provider failures.")
    for segment_id, message in result.errors[:5]:
        console.print(f"[yellow]failed[/yellow] {segment_id}: {message}")
    if len(result.errors) > 5:
        console.print(f"[yellow]... and {len(result.errors) - 5} more[/yellow]")


@app.command()
def describe(
    project: Annotated[Path, typer.Argument(help="Output folder holding manifest.json.")],
    scope: Annotated[
        str | None,
        typer.Option("--scope", help="Segments to describe: candidates or selected."),
    ] = None,
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Ask a hosted vision model for tags, a caption and an aesthetic per segment."""
    cfg = _load_config(config, no_cloud)
    if scope is not None:
        if scope not in ("candidates", "selected"):
            console.print(f"[red]Unknown scope[/red] {scope!r}. Use candidates or selected.")
            raise typer.Exit(code=2)
        cfg.providers.describe_scope = scope  # type: ignore[assignment]
    manifest = _open_project(project)
    result = _run_describe(manifest, cfg, no_cloud)
    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    _print_describe(result)


key_app = typer.Typer(name="key", help="Store the provider API key in the OS keychain.")
app.add_typer(key_app)


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
        console.print("[red]No key given[/red]; nothing was stored.")
        raise typer.Exit(code=2)
    try:
        set_key(secret.strip())
    except Exception as exc:  # noqa: BLE001 - any keyring backend failure reads the same
        console.print(f"[red]Could not store the key[/red]: {exc}")
        raise typer.Exit(code=1) from exc
    console.print("Key stored in the keychain as autocut/openrouter.")


@key_app.command("clear")
def key_clear() -> None:
    """Remove the stored key. The environment variable, if set, still wins."""
    if clear_key():
        console.print("Key removed from the keychain.")
    else:
        console.print("No key was stored in the keychain.")


@app.command()
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
    report = inspect_environment(_load_config(config, no_cloud), sample)
    if as_json:
        # Written straight to stdout: Rich would soft wrap a long cache path and the
        # output has to parse.
        typer.echo(json.dumps(report.as_dict(), indent=2))
    else:
        for check in report.checks:
            colour = "green" if check.ok else "yellow"
            console.print(f"[{colour}]{check.marker:>7}[/{colour}] {check.name}: {check.detail}")
    if not report.ok:
        raise typer.Exit(code=1)


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
    no_cloud: NoCloudOpt = False,
) -> None:
    """Pick the best window per segment and the final diverse set of clips."""
    cfg = _load_config(config, no_cloud)
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
    if result.held_by_tag:
        console.print(
            f"  {result.held_by_tag} candidates held back by the tag share cap "
            f"of {cfg.selection.max_share_per_tag:g}"
        )
    if result.lifted_tag_cap:
        console.print(
            "[yellow]The tag share cap was lifted[/yellow]: no candidate with another "
            "subject was left."
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
    cfg = _load_config(config, no_cloud)
    manifest = _open_project(project)
    manifest.output_dir = project

    provider, reason = _text_provider(cfg, no_cloud)
    try:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
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
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=2) from exc
    finally:
        if provider is not None:
            provider.close()

    if result.skipped:
        console.print(f"[red]{result.skipped_reason}[/red]")
        raise typer.Exit(code=1)

    manifest.updated_at = datetime.now(UTC)
    manifest.save(project / "manifest.json")
    _print_soundtrack(result, reason)


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


def _print_soundtrack(result: SoundtrackResult, reason: str) -> None:
    matched = result.matched
    if matched is not None:
        console.print(
            f"Genre [bold]{matched.row.genre}[/bold] from row {matched.row.name!r}: "
            f"{matched.reason}"
        )
    console.print(
        f"Proposed BPM [bold]{result.bpm}[/bold], mean distance from a whole beat "
        f"{result.beat_distance:.3f} beats, {result.shape} energy shape"
    )
    console.print(f"Wrote [bold]{len(result.variants)}[/bold] variants to {result.prompt_path}")
    if result.dropped:
        console.print(
            f"  {len(result.dropped)} candidate variants failed validation and were dropped"
        )
    geocode = result.geocode
    if geocode is not None:
        if geocode.skipped_reason is not None:
            console.print(f"  Place names skipped: {geocode.skipped_reason}")
        elif geocode.requests or geocode.from_cache:
            console.print(
                f"  Named {geocode.named} places ({geocode.from_cache} from cache, "
                f"{geocode.requests} looked up)"
            )
        for warning in geocode.warnings:
            console.print(f"[yellow]{warning}[/yellow]")
    if result.refinement == "accepted":
        console.print(f"  Refinement accepted, {result.cost_usd:.4f} USD")
    elif result.refinement == "rejected":
        console.print(f"[yellow]Refinement rejected[/yellow]: {result.refinement_note}")
    elif result.refinement == "failed":
        console.print(f"[yellow]Refinement failed[/yellow]: {result.refinement_note}")
    elif result.refinement == "off":
        console.print(f"  Refinement off: {result.refinement_note}")
    else:
        console.print(f"  Refinement skipped: {result.refinement_note or reason}")


@app.command()
def report(
    project: Annotated[Path, typer.Argument()],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
) -> None:
    """Write report.html for visual review."""
    _load_config(config, no_cloud)
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
    no_cloud: NoCloudOpt = False,
) -> None:
    """Measure the track BPM and quantize clip durations to beats."""
    cfg = _load_config(config, no_cloud)
    manifest = _open_project(project)
    manifest.output_dir = project

    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    if not selected:
        console.print("[red]Nothing selected[/red]. Run autocut select first.")
        raise typer.Exit(code=1)
    if not audio.exists():
        console.print(f"[red]No such track[/red]: {audio}")
        raise typer.Exit(code=1)

    # A re-run is a fresh measurement, not a drift on top of the last one.
    reset_final_bounds(manifest)
    try:
        track = measure_track(decode_audio(audio))
    except AudioUnavailableError as exc:
        console.print(f"[red]{exc}[/red]")
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
        console=console,
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

    _print_sync(track, effective, comparison, result, beatmap, override=bpm is not None)


def _print_sync(
    track: Track,
    effective: float,
    comparison: object,
    result: QuantizeResult,
    beatmap: Path,
    override: bool,
) -> None:
    status = getattr(comparison, "status", "")
    note = getattr(comparison, "note", None)
    console.print(
        f"Measured [bold]{track.bpm:g}[/bold] bpm from {len(track.beats_s)} beats"
        + (f", using [bold]{effective:g}[/bold] as asked" if override else "")
    )
    if track.tempo_estimate and abs(track.tempo_estimate - track.bpm) > 1:
        console.print(
            f"  librosa's own tempo estimate was {track.tempo_estimate:g}; the beat "
            "spacing is what the clips are cut to"
        )
    if status in ("drifted", "half", "double"):
        console.print(f"[yellow]{note}[/yellow]")
    elif note:
        console.print(f"  {note}")
    console.print(
        f"Quantized [bold]{result.clips}[/bold] clips, "
        f"{result.total_before_s:.1f} s to [bold]{result.total_after_s:.1f} s[/bold] "
        f"({result.drift_s:+.1f} s), mean move {result.mean_shift_s:.2f} s"
    )
    spread = ", ".join(f"{count}x{multiple}" for multiple, count in result.per_multiple.items())
    console.print(f"  beats per clip: {spread}")
    if result.clamped:
        console.print(
            f"  {result.clamped} clips were clamped to a shorter multiple by their own span"
        )
    if result.off_grid:
        console.print(
            f"  {result.off_grid} clips are too short to start on a sampled instant and "
            "keep their own bounds instead"
        )
    console.print(f"Beat map written to {beatmap}")


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
    no_cloud: NoCloudOpt = False,
) -> None:
    """Cut, normalize and write the numbered clips into _selects/."""
    cfg = _load_config(config, no_cloud)
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
def gui(
    project: Annotated[
        Path | None,
        typer.Argument(help="Project folder to open on start. Optional."),
    ] = None,
) -> None:
    """Open the desktop window. Needs the gui extra."""
    try:
        from autocut.gui.app import run as run_gui
    except ImportError as error:
        console.print(
            "[red]The gui extra is not installed.[/red] Install it with: "
            # Escaped, because the one part of this line the user has to type
            # verbatim is the part Rich would read as markup and eat.
            r'pip install -e ".\[gui]"'
        )
        console.print(f"  {error}")
        raise typer.Exit(code=1) from error
    raise typer.Exit(code=run_gui(project))


@app.command()
def run(
    sources: Annotated[list[Path], typer.Argument()],
    out: Annotated[Path, typer.Option("--out", "-o")],
    config: ConfigOpt = None,
    no_cloud: NoCloudOpt = False,
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
    soundtrack(project=out, config=config, no_cloud=no_cloud)
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

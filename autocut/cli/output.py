"""The console and every command's printed summary.

Every command reaches the console through ``output.console`` at call time, never by
importing the name, so a test's monkeypatch of this module's ``console`` attribute
reaches every command regardless of which module it runs in.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from autocut.core.beatsync import QuantizeResult, Track
from autocut.core.describe import DescribeResult
from autocut.core.embeddings import EmbedResult
from autocut.core.render import RenderResult
from autocut.core.soundtrack.build import SoundtrackResult
from autocut.core.tags import TagResult

console = Console()


def print_embed(result: EmbedResult) -> None:
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


def print_tag(result: TagResult) -> None:
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


def print_describe(result: DescribeResult) -> None:
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


def print_soundtrack(result: SoundtrackResult, reason: str) -> None:
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


def print_sync(
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


def print_render(result: RenderResult) -> None:
    if result.skipped_reason:
        console.print(f"[yellow]Nothing rendered[/yellow]: {result.skipped_reason}")
        return
    if result.export is not None:
        console.print(
            f"Exported [bold]{result.export.exported}[/bold] clips first, "
            f"{result.export.skipped} were already current"
        )
    for where, error in result.errors:
        console.print(f"[red]{where}[/red]: {error}")
    if not result.ok:
        return
    if result.reused:
        console.print(f"Nothing changed since the last render: {result.path}")
        return
    if result.frame[0] and result.frame[1]:
        console.print(f"Clips exported at one size, {result.frame[0]}x{result.frame[1]}")
    console.print(
        f"Rendered [bold]{result.clips}[/bold] clips, "
        f"[bold]{result.duration_s:.1f} s[/bold], {result.size_bytes / 1e6:.0f} MB "
        f"to {result.path}"
    )
    if result.track is not None:
        console.print(f"  track {result.track.name}, {result.fade_out_s:g} s fade out")
    elif result.has_audio:
        console.print("  the clips' own audio, since no track was given")
    else:
        console.print("  no audio: the clips are silent and no track was given")
    console.print("  hard cuts only; anything that needs a transition belongs in an editor")

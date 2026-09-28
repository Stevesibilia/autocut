"""The ``select`` command: the best window per segment and the final diverse set."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from autocut.cli import output
from autocut.cli.common import ConfigOpt, NoCloudOpt, load_config, open_project
from autocut.core.select import SelectionOverrides, select_clips


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
    cfg = load_config(config, no_cloud)
    manifest = open_project(project)
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
    output.console.print(
        f"Selected [bold]{result.count}[/bold] of {result.max_clips} clips "
        f"from {result.clusters} clusters, diversity {result.diversity_lambda:g}"
    )
    output.console.print(f"  {result.places} places, {result.visits} visits")
    if result.held_by_place:
        output.console.print(
            f"  {result.held_by_place} candidates held back by the place cap "
            f"of {cfg.selection.max_clips_per_place} per visit"
        )
    if result.held_by_tag:
        output.console.print(
            f"  {result.held_by_tag} candidates held back by the tag share cap "
            f"of {cfg.selection.max_share_per_tag:g}"
        )
    if result.lifted_tag_cap:
        output.console.print(
            "[yellow]The tag share cap was lifted[/yellow]: no candidate with another "
            "subject was left."
        )
    if result.ceiling_applied:
        output.console.print(
            f"[yellow]The candidate share ceiling applied[/yellow]: at most "
            f"{cfg.selection.max_candidate_share:g} of the eligible candidates, so "
            f"{result.max_clips} slots. Pass --max-clips to override it."
        )
    for name, count in sorted(per_class.items()):
        output.console.print(f"  {name}: {count}")
    if result.varied_durations:
        output.console.print(
            f"Total [bold]{result.total_duration_s:.1f} s[/bold]: "
            f"{result.long_clips} long, {result.short_clips} short, {result.hero_clips} hero"
        )
    else:
        output.console.print(
            f"Total [bold]{result.total_duration_s:.1f} s[/bold], one length for every clip"
        )
    if abs(result.total_shortfall_s) > 0.05:
        output.console.print(
            f"[yellow]The total target was missed by {result.total_shortfall_s:+.1f} s[/yellow]; "
            "the duration bounds were reached first."
        )
    snapped = sum(1 for s in manifest.segments.values() if s.outcome == "selected" and s.snapped)
    if snapped:
        output.console.print(f"  {snapped} windows moved onto a motion boundary")
    if result.relaxed_gap:
        output.console.print(
            "[yellow]The minimum temporal gap was relaxed[/yellow] to fill the remaining slots."
        )

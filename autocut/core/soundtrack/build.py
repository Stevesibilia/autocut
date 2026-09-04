"""From a selected edit to a written, validated prompt file.

One function ties the parts together, so the CLI stays a renderer and the GUI in M5 can
call the same thing. The order matters and is the order the design gives: name the
places, derive the signals, match a row, fit a BPM to the durations the edit actually
uses, write the variants, validate every one, then optionally ask a model to improve the
first and validate that too.

A variant that does not validate is never written. That is the point of generating more
than one: the file the user pastes from has only prompts that follow the rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from autocut.core.config import AutocutConfig, GenreRow
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.geocode import GeocodeResult, geocode_places
from autocut.core.manifest import Manifest, PromptVariant, SoundtrackSignals
from autocut.core.providers import TextProvider
from autocut.core.soundtrack.genres import Match, match_row
from autocut.core.soundtrack.prompt import build_prompt, energy_shape, propose_bpm
from autocut.core.soundtrack.refine import refine_prompt
from autocut.core.soundtrack.signals import clip_durations, derive_signals
from autocut.core.soundtrack.validate import Validation, validate_prompt

PROMPT_FILENAME = "suno-prompt.md"

#: Tried in order until enough valid variants exist. A row with three moods and one
#: alternate instrument gives six distinct palettes, which is more than the five the
#: spec allows anyone to ask for.
MAX_VARIANT_ATTEMPTS = 12


@dataclass(slots=True)
class SoundtrackResult:
    """What one soundtrack pass produced."""

    matched: Match | None = None
    bpm: int = 0
    beat_distance: float = 0.0
    shape: str = "flat"
    variants: list[PromptVariant] = field(default_factory=list)
    dropped: list[list[str]] = field(default_factory=list)
    prompt_path: Path | None = None
    geocode: GeocodeResult | None = None
    refinement: str = "off"
    refinement_note: str | None = None
    requests: int = 0
    cost_usd: float = 0.0
    skipped_reason: str | None = None

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


def build_soundtrack(
    manifest: Manifest,
    config: AutocutConfig,
    provider: TextProvider | None = None,
    progress: ProgressCallback = null_progress,
    bpm_override: int | None = None,
    genre_override: str | None = None,
    variants: int | None = None,
    geocode: bool = True,
    refine_note: str | None = None,
) -> SoundtrackResult:
    """Write the prompt file for a selected project and record it on the manifest."""
    selected = [s for s in manifest.segments.values() if s.outcome == "selected"]
    if not selected:
        return SoundtrackResult(skipped_reason="nothing is selected, run autocut select first")

    result = SoundtrackResult()
    if geocode:
        result.geocode = geocode_places(manifest, config, progress=progress)

    signals = derive_signals(manifest, config)
    manifest.soundtrack.signals = signals

    matched = _match(signals, config, genre_override)
    result.matched = matched
    result.shape = energy_shape(signals)

    durations = clip_durations(manifest)
    proposal = propose_bpm(durations, matched.row, config)
    result.bpm = bpm_override if bpm_override is not None else proposal.bpm
    result.beat_distance = (
        proposal.beat_distance
        if bpm_override is None
        else _distance_at(durations, result.bpm, config)
    )

    wanted = variants if variants is not None else config.soundtrack.variants
    result.variants, result.dropped = _valid_variants(
        signals, matched.row, result.bpm, config, wanted, progress
    )

    if provider is not None and result.variants:
        _refine_first(signals, result, config, provider)
    else:
        # Two states, not one: "off" is the user switching it off, "skipped" is it being
        # on and unable to run. The manifest and the CLI have to agree on which.
        if not config.soundtrack.refine:
            result.refinement = "off"
            result.refinement_note = "soundtrack.refine is false"
        else:
            result.refinement = "skipped"
            result.refinement_note = refine_note or "no text provider was available"

    _record(manifest, result, matched)
    result.prompt_path = write_prompt_file(manifest, result)
    manifest.soundtrack.prompt_path = result.prompt_path
    return result


def _match(signals: SoundtrackSignals, config: AutocutConfig, genre_override: str | None) -> Match:
    """The matched row, or the one the user named on the command line."""
    if genre_override is not None:
        wanted = genre_override.strip().lower()
        for row in config.soundtrack.genres:
            if wanted in (row.name.lower(), row.genre.lower()):
                return Match(row=row, reason=f"asked for {genre_override!r} on the command line")
        known = ", ".join(row.name for row in config.soundtrack.genres)
        raise ValueError(f"unknown genre {genre_override!r}; the table has: {known}")
    return match_row(signals, config)


def _distance_at(durations: list[float], bpm: int, config: AutocutConfig) -> float:
    """How well an overridden BPM fits, so the report can say even when it was forced."""
    row = GenreRow(name="override", genre="override", instruments=[], bpm=(bpm, bpm), mood=[])
    return propose_bpm(durations, row, config).beat_distance


def _valid_variants(
    signals: SoundtrackSignals,
    row: GenreRow,
    bpm: int,
    config: AutocutConfig,
    wanted: int,
    progress: ProgressCallback,
) -> tuple[list[PromptVariant], list[list[str]]]:
    """As many distinct valid variants as asked for, and the reasons any were dropped."""
    kept: list[PromptVariant] = []
    dropped: list[list[str]] = []
    seen: set[str] = set()
    for attempt in range(MAX_VARIANT_ATTEMPTS):
        if len(kept) >= wanted:
            break
        candidate = build_prompt(signals, row, bpm, config, attempt)
        if candidate.description in seen:
            continue
        verdict = validate_prompt(
            candidate.description, candidate.structure, config, tuple(candidate.instruments)
        )
        if verdict.ok:
            seen.add(candidate.description)
            kept.append(candidate)
            progress(ProgressEvent(stage="soundtrack", current=len(kept), total=wanted))
        else:
            dropped.append(verdict.reasons)
    return kept, dropped


def _refine_first(
    signals: SoundtrackSignals,
    result: SoundtrackResult,
    config: AutocutConfig,
    provider: TextProvider,
) -> None:
    """Try to improve the first variant. Every failure keeps the template."""
    if not config.soundtrack.refine:
        result.refinement = "skipped"
        result.refinement_note = "soundtrack.refine is false"
        return
    outcome = refine_prompt(signals, result.variants[0], result.bpm, config, provider)
    result.refinement = outcome.status
    result.refinement_note = outcome.note
    result.requests += outcome.requests
    result.cost_usd += outcome.cost_usd
    if outcome.status == "accepted" and outcome.prompt is not None:
        result.variants.insert(0, outcome.prompt)


def store_user_variant(
    manifest: Manifest, variant: PromptVariant, config: AutocutConfig
) -> Validation:
    """Keep a hand edited prompt, if it validates, and make it the chosen one.

    Stored first in the list rather than appended, so it is the prompt the file opens
    with and the one every later step reads. An invalid prompt is not stored at all:
    the point of the validator is that nothing unusable reaches Suno, and a prompt kept
    "for later" would be exactly that.

    Any earlier user variant is replaced. A person editing twice means the second one.
    """
    verdict = validate_prompt(
        variant.description, variant.structure, config, tuple(variant.instruments)
    )
    if not verdict.ok:
        return verdict
    stored = variant.model_copy(update={"source": "user"})
    generated = [item for item in manifest.soundtrack.variants if item.source != "user"]
    manifest.soundtrack.variants = [stored, *generated]
    manifest.soundtrack.chosen_variant = 0
    return verdict


def _record(manifest: Manifest, result: SoundtrackResult, matched: Match) -> None:
    manifest.soundtrack.matched_row = matched.row.name
    manifest.soundtrack.matched_reason = matched.reason
    manifest.soundtrack.genre = matched.row.genre
    manifest.soundtrack.proposed_bpm = float(result.bpm)
    manifest.soundtrack.beat_distance = round(result.beat_distance, 4)
    # A hand edited prompt survives a regeneration and stays first: the user wrote it
    # after seeing what the template produced, so the template does not get to win.
    kept = [item for item in manifest.soundtrack.variants if item.source == "user"]
    manifest.soundtrack.variants = [*kept, *result.variants]
    manifest.soundtrack.chosen_variant = 0
    manifest.soundtrack.refinement = result.refinement  # type: ignore[assignment]
    manifest.soundtrack.refinement_note = result.refinement_note


def write_prompt_file(manifest: Manifest, result: SoundtrackResult) -> Path:
    """``suno-prompt.md``: copy-ready blocks, the BPM, and how the genre was chosen."""
    signals = manifest.soundtrack.signals
    lines: list[str] = ["# Soundtrack prompt", ""]
    if signals is not None:
        lines += [
            f"{signals.clip_count} clips, {signals.total_duration_s:.1f} s, "
            f"{signals.energy_band} energy, {signals.time_of_day}.",
            "",
        ]
    if result.matched is not None:
        lines += [
            f"**Genre:** {result.matched.row.genre} "
            f"(row `{result.matched.row.name}`: {result.matched.reason})",
            "",
        ]
    lines += [
        f"**Proposed BPM:** {result.bpm}. Mean distance from a whole beat: "
        f"{result.beat_distance:.3f} beats.",
        "",
        "Suno custom mode: Description goes in the style field, Structure in the lyrics field.",
        "",
    ]
    written = manifest.soundtrack.variants or list(result.variants)
    for number, variant in enumerate(written, start=1):
        label = {"refined": "refined", "user": "yours, edited by hand"}.get(
            variant.source, "template"
        )
        lines += [f"## Variant {number} ({label})", "", "**Title**", "", variant.title, ""]
        lines += ["**Description**", "", variant.description, "", "**Structure**", "", "```"]
        lines += list(variant.structure)
        lines += ["```", ""]
    if result.dropped:
        lines += [
            f"{len(result.dropped)} generated variants were dropped for failing "
            "validation and are not shown.",
            "",
        ]
    path = Path(manifest.output_dir) / PROMPT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path

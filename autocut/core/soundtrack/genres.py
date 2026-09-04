"""Choosing the genre row that describes this edit.

First match wins over an ordered table, and the row that won is recorded with the
condition that made it win. The alternative, scoring every row and taking the best, was
rejected in the design for one reason: the report has to be able to say "surf rock,
because the dominant tag is beach, underwater is present and the energy is mid", and a
weighted sum cannot say that.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocut.core.config import AutocutConfig, GenreRow, GenreWhen
from autocut.core.manifest import SoundtrackSignals


@dataclass(slots=True)
class Match:
    """The row that won and why, or the default row and why nothing else did."""

    row: GenreRow
    reason: str
    matched: bool = True


def _conditions(when: GenreWhen, signals: SoundtrackSignals) -> list[tuple[bool, str]]:
    """Every condition the row states, each with whether it holds and how to say it."""
    checks: list[tuple[bool, str]] = []
    if when.tags_dominant:
        wanted = ", ".join(when.tags_dominant)
        checks.append(
            (
                signals.dominant_tag in when.tags_dominant,
                f"dominant tag is {signals.dominant_tag or 'none'} (wants {wanted})",
            )
        )
    if when.tags_any:
        present = [tag for tag in when.tags_any if signals.tags.get(tag)]
        checks.append(
            (
                bool(present),
                f"{', '.join(present)} present"
                if present
                else f"none of {', '.join(when.tags_any)}",
            )
        )
    for name, minimum in when.class_min_share.items():
        share = signals.class_mix.get(name, 0.0)
        checks.append((share >= minimum, f"{name} share {share:.2f} (wants {minimum:.2f})"))
    if when.energy:
        checks.append(
            (
                signals.energy_band in when.energy,
                f"energy {signals.energy_band} (wants {' or '.join(when.energy)})",
            )
        )
    if when.time_of_day:
        checks.append(
            (
                signals.time_of_day in when.time_of_day,
                f"time of day {signals.time_of_day} (wants {' or '.join(when.time_of_day)})",
            )
        )
    if when.region_any:
        haystack = " ".join(signals.regions).lower()
        hit = next((word for word in when.region_any if word.lower() in haystack), None)
        checks.append((hit is not None, f"region {hit}" if hit else "no matching region"))
    return checks


def match_row(signals: SoundtrackSignals, config: AutocutConfig) -> Match:
    """The first row whose every condition holds, or the named default.

    A row with no conditions matches anything, so a table whose last row is bare never
    reaches the default lookup. Both paths are recorded the same way.
    """
    rows = config.soundtrack.genres
    for row in rows:
        checks = _conditions(row.when, signals)
        if all(held for held, _ in checks):
            reason = "; ".join(text for _, text in checks) or "no conditions, matches anything"
            return Match(row=row, reason=reason)

    wanted = config.soundtrack.default_profile
    fallback = next((row for row in rows if row.name == wanted), None)
    if fallback is None:
        if not rows:
            raise ValueError("soundtrack.genres is empty and there is nothing to fall back to")
        fallback = rows[-1]
        return Match(
            row=fallback,
            reason=(
                f"no row matched and the default profile {wanted!r} is not in the table, "
                f"so the last row {fallback.name!r} was used"
            ),
            matched=False,
        )
    return Match(
        row=fallback,
        reason=f"no row matched, so the default profile {wanted!r} was used",
        matched=False,
    )

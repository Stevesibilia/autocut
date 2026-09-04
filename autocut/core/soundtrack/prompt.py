"""Writing the Title, Description and Structure blocks, and proposing a BPM.

Both halves are built to satisfy :mod:`validate` by construction rather than by luck:
the Description carries exactly the seven descriptors the rules allow, and the Structure
covers each named instrument twice because the modifier plan places it twice. The
validator still runs on the result, because a rule that is only honoured by construction
is a rule that breaks the first time the construction changes.

The arc is the edit's own. A structure whose peak sits in the middle when the footage
peaks at the end would give the music a shape the video does not have, which is the one
thing SPEC.md section 7.5 is emphatic about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from autocut.core.config import AutocutConfig, GenreRow
from autocut.core.manifest import PromptVariant, SoundtrackSignals
from autocut.core.soundtrack.validate import INSTRUMENTAL_SUFFIX, instrument_noun

#: Description names two instruments, not three. Seven descriptors is the maximum the
#: rules allow and genre, mood, BPM and the two closing markers already take five.
INSTRUMENTS_IN_DESCRIPTION = 2

#: Below this spread between the thirds of the energy curve there is no arc to follow,
#: and inventing one would give the music a shape the edit has not got.
FLAT_SPREAD = 0.1

#: One skeleton per shape: the section words in order, and how many tags each takes.
#: Every count is inside the 3 to 6 the rules allow, and every word is in the shipped
#: allowed list.
SKELETONS: dict[str, tuple[tuple[str, int], ...]] = {
    "flat": (("intro", 3), ("verse", 3), ("chorus", 3), ("outro", 3)),
    "front": (("intro", 3), ("chorus", 3), ("verse", 3), ("break", 3), ("outro", 3)),
    "peak-middle": (("intro", 3), ("build", 3), ("chorus", 4), ("break", 3), ("outro", 3)),
    "peak-late": (("intro", 3), ("verse", 3), ("build", 3), ("drop", 4), ("outro", 3)),
}

#: Modifiers that describe how a section moves. One per section, cycled, so a section
#: never repeats a word and the four dimensions the rules ask for are all present.
ENERGY_WORDS: dict[str, tuple[str, ...]] = {
    "intro": ("sparse", "slow", "gentle"),
    "verse": ("steady", "walking", "easy"),
    "build": ("rising", "tightening", "urgent"),
    "chorus": ("wide", "full", "soaring"),
    "drop": ("driving", "pounding", "relentless"),
    "break": ("quiet", "stripped", "floating"),
    "outro": ("fading", "settling", "calm"),
}


@dataclass(slots=True)
class BpmProposal:
    """The BPM that fits the edit best, and how well it fits."""

    bpm: int
    beat_distance: float


def energy_shape(signals: SoundtrackSignals, flat_spread: float = FLAT_SPREAD) -> str:
    """Which skeleton this edit's energy asks for.

    Four shapes, as the design says, with one renamed: a peak in the last third is a
    rising edit, so "rising" and "peak-late" would be the same skeleton. The fourth
    shape is instead "front", an edit that opens at its loudest and has nowhere to
    build to, which the Sardinia material does produce.
    """
    curve = signals.energy_curve
    if not curve:
        return "flat"
    thirds = _thirds(curve)
    if max(thirds) - min(thirds) < flat_spread:
        return "flat"
    return {0: "front", 1: "peak-middle", 2: "peak-late"}[signals.peak_third]


def _thirds(curve: list[float]) -> list[float]:
    size = max(len(curve) // 3, 1)
    parts = [curve[:size], curve[size : size * 2], curve[size * 2 :]]
    return [sum(part) / len(part) if part else 0.0 for part in parts]


def propose_bpm(durations: list[float], row: GenreRow, config: AutocutConfig) -> BpmProposal:
    """The BPM in the row's range whose beat grid the clip lengths sit closest to.

    Cost is the mean distance, in beats, from each clip's length to the nearest allowed
    beat multiple. A clip of 2.0 s at 120 BPM is exactly four beats and costs nothing,
    which is the case the spec names. Ties go to the middle of the range, because the
    edges of a genre's range are where it stops sounding like itself.
    """
    low, high = row.bpm
    low, high = min(low, high), max(low, high)
    multiples = [m for m in config.soundtrack.beat_multiples if m > 0] or [4]
    centre = (low + high) / 2.0
    best: BpmProposal | None = None
    best_key: tuple[float, float] | None = None
    for bpm in range(int(low), int(high) + 1):
        cost = _beat_distance(durations, bpm, multiples)
        key = (round(cost, 9), abs(bpm - centre))
        if best_key is None or key < best_key:
            best, best_key = BpmProposal(bpm=bpm, beat_distance=cost), key
    assert best is not None
    return best


def _beat_distance(durations: list[float], bpm: int, multiples: list[int]) -> float:
    """Mean distance in beats from each clip length to the nearest allowed multiple."""
    if not durations:
        return 0.0
    total = 0.0
    for duration in durations:
        beats = duration * bpm / 60.0
        total += min(abs(beats - multiple) for multiple in multiples)
    return total / len(durations)


def title_for(signals: SoundtrackSignals, row: GenreRow) -> str:
    """A short lowercase title: where it was, or what it shows, and the genre."""
    subject = None
    if signals.place_names:
        subject = signals.place_names[0]
    elif signals.dominant_tag:
        subject = signals.dominant_tag
    parts = [part for part in (subject, signals.time_of_day, row.genre) if part]
    return ", ".join(part.lower() for part in parts)


def _section_moods(row: GenreRow, chosen: str, count: int) -> list[str]:
    """One mood word per section, the variant's own first, then the row's others.

    The first version used the same word in every section, so a five section structure
    read "sunny" five times. A tag is meant to cover a dimension the others do not, and
    a repeated mood wastes four of them.
    """
    pool = [chosen, *[word for word in (*row.mood, *row.mood_alternates) if word != chosen]]
    return [pool[index % len(pool)] for index in range(count)]


def _variant_palette(row: GenreRow, index: int) -> tuple[list[str], str]:
    """The instruments and the mood word this variant uses.

    Variants share genre and BPM and differ in mood or instrumentation, so the choice
    walks the row's own alternates rather than inventing anything.
    """
    moods = [*row.mood, *row.mood_alternates] or ["warm"]
    instruments = list(row.instruments)
    alternates = list(row.instrument_alternates)
    mood = moods[index % len(moods)]
    chosen = instruments[:INSTRUMENTS_IN_DESCRIPTION]
    if index and alternates:
        swap = alternates[(index - 1) % len(alternates)]
        # Swapping the first keeps the rhythm section, which is what holds a genre.
        chosen = [swap, *instruments[1:INSTRUMENTS_IN_DESCRIPTION]]
    elif index and len(instruments) > INSTRUMENTS_IN_DESCRIPTION:
        chosen = [
            instruments[INSTRUMENTS_IN_DESCRIPTION],
            *instruments[1:INSTRUMENTS_IN_DESCRIPTION],
        ]
    return chosen, mood


def build_description(row: GenreRow, bpm: int, instruments: list[str], mood: str) -> str:
    """Genre, instruments, mood, BPM, then the two closing markers. Seven descriptors."""
    parts = [row.genre, *instruments, mood, f"{bpm} bpm", *INSTRUMENTAL_SUFFIX]
    return ", ".join(parts)


def build_structure(
    shape: str, instruments: list[str], mood: str, moods: list[str] | None = None
) -> list[str]:
    """One bracketed tag per line, ending in ``[end]``.

    Each section takes its energy word first, then cycles the instrument nouns and the
    mood, so every named instrument lands at least twice across the whole structure and
    no section repeats a modifier.

    The section words come from :data:`SKELETONS` and are all in the shipped
    ``soundtrack.allowed_sections``. That setting exists because the rules are Suno's and
    Suno changes them, so it is there to widen or rename the list. Narrowing it below
    what these skeletons use is reported by the validator rather than worked around
    here: a prompt quietly reshaped to fit a trimmed list would be a prompt the user did
    not ask for.
    """
    nouns = [
        instrument_noun(instrument) for instrument in instruments if instrument_noun(instrument)
    ]
    skeleton = SKELETONS.get(shape, SKELETONS["flat"])
    # One mood word per section rather than one for the whole structure.
    section_moods = moods if moods is not None else [mood] * len(skeleton)
    lines: list[str] = []
    noun_cursor = 0
    for index, (section, count) in enumerate(skeleton):
        energy = ENERGY_WORDS.get(section, ("steady", "open", "clear"))
        section_mood = section_moods[index % len(section_moods)] if section_moods else mood
        used: list[str] = []
        for position in range(count):
            if position == 0:
                modifier = energy[0]
            elif position == 1 and nouns:
                modifier = nouns[noun_cursor % len(nouns)]
                noun_cursor += 1
            elif position == 2:
                modifier = section_mood
            else:
                modifier = energy[min(position - 2, len(energy) - 1)]
            if modifier in used:
                # Never repeat a modifier inside one section: the rules ask each tag to
                # cover a different dimension.
                pool = [*energy, *nouns, section_mood, mood]
                modifier = next((word for word in pool if word not in used), modifier)
            used.append(modifier)
            lines.append(f"[{modifier} {section}]")
    lines.append("[end]")
    return lines


#: The three positions of a mood control. Named rather than numeric because a caller
#: reading ``apply_mood(..., calm=-1)`` has to look up what -1 meant.
MoodDirection = Literal["calmer", "keep", "energetic"]
RoomDirection = Literal["intimate", "keep", "cinematic"]


def _pick_by_scale(pool: list[str], scale: list[str], toward_end: bool) -> str:
    """The word from ``pool`` furthest along ``scale``, or furthest back.

    A word missing from the scale is neutral: it takes the middle position rather than
    an end, because the scales are a way of choosing between words a row already offers
    and not a claim to rank every word in English. With nothing to go on the first word
    of the pool wins, which is the row's own default.
    """
    if not pool:
        return ""
    middle = len(scale) / 2.0

    def position(word: str) -> float:
        return float(scale.index(word)) if word in scale else middle

    ranked = sorted(pool, key=lambda word: (position(word), pool.index(word)))
    return ranked[-1] if toward_end else ranked[0]


def apply_mood(
    variant: PromptVariant,
    row: GenreRow,
    bpm: int,
    signals: SoundtrackSignals,
    config: AutocutConfig,
    calm: MoodDirection = "keep",
    room: RoomDirection = "keep",
) -> PromptVariant:
    """The same prompt with a different mood word, chosen inside the matched row.

    The two controls of SPEC.md section 11, calmer to more energetic and cinematic to
    intimate, pick between the mood words the row already carries and never change the
    genre: a row is a claim about what this footage sounds like, and a slider is not the
    place to overrule it. Both axes read the same pool, so asking for calmer and
    intimate at once can land on one word that is both, which is the honest answer
    rather than two words fighting.

    Rebuilt rather than patched, because the Structure spreads the mood across its
    sections and editing the Description alone would leave the two blocks disagreeing.
    """
    pool = [*row.mood, *row.mood_alternates] or [variant.mood[0] if variant.mood else "warm"]
    chosen = variant.mood[0] if variant.mood else pool[0]
    if calm != "keep":
        chosen = _pick_by_scale(pool, config.soundtrack.calm_to_energetic, calm == "energetic")
    if room != "keep":
        # The room axis reads the pool the first axis narrowed to, so two moves compose
        # instead of the second one throwing the first away.
        candidates = [chosen] if calm != "keep" else pool
        chosen = _pick_by_scale(
            candidates or pool, config.soundtrack.intimate_to_cinematic, room == "cinematic"
        )
    shape = energy_shape(signals)
    skeleton = SKELETONS.get(shape, SKELETONS["flat"])
    moods = _section_moods(row, chosen, len(skeleton))
    return PromptVariant(
        title=variant.title,
        description=build_description(row, bpm, variant.instruments, chosen),
        structure=build_structure(shape, variant.instruments, chosen, moods),
        mood=moods,
        instruments=variant.instruments,
        source=variant.source if variant.source != "user" else "template",
    )


def build_prompt(
    signals: SoundtrackSignals,
    row: GenreRow,
    bpm: int,
    config: AutocutConfig,
    variant: int = 0,
) -> PromptVariant:
    """One complete prompt. Validation is the caller's job and is never skipped."""
    instruments, mood = _variant_palette(row, variant)
    shape = energy_shape(signals)
    skeleton = SKELETONS.get(shape, SKELETONS["flat"])
    moods = _section_moods(row, mood, len(skeleton))
    return PromptVariant(
        title=title_for(signals, row),
        # The Description names the variant's own mood; the Structure moves through the
        # row's others section by section.
        description=build_description(row, bpm, instruments, mood),
        structure=build_structure(shape, instruments, mood, moods),
        mood=moods,
        instruments=instruments,
        source="template",
    )

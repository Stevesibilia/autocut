"""The one gate every prompt passes through, whoever wrote it.

A malformed Suno prompt produces wrong music and the mistake is invisible by eye: a
comma inside a bracket reads fine to a person and changes what the model hears. So the
rules from SPEC.md section 7.5 are checked mechanically, and the same function checks
the template output and anything a hosted model sends back.

Every violation is returned, not the first, because a GUI has to mark all of them and
because a caller deciding whether to keep a refinement wants the whole list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from autocut.core.config import AutocutConfig

#: The two descriptors a Description has to end with, in this order.
INSTRUMENTAL_SUFFIX = ("no vocals", "instrumental")

MIN_DESCRIPTORS = 4
MAX_DESCRIPTORS = 7
MIN_SECTION_TAGS = 3
MAX_SECTION_TAGS = 6
MAX_DESCRIPTOR_WORDS = 5

#: Words that mean a voice. `verse` is not here: it is a legal section word, and what
#: makes it vocal is a lyric line after it, which is checked separately.
VOCAL_WORDS: tuple[str, ...] = (
    "vocal",
    "vocals",
    "choir",
    "singing",
    "sung",
    "rap",
    "lyrics",
    "acappella",
    "a cappella",
)

#: From SPEC.md section 7.5: these belong in Description next to their instrument, where
#: they describe a sound, not in Structure, where they would describe a section.
PRODUCTION_WORDS: tuple[str, ...] = (
    "filtered",
    "sidechained",
    "punchy",
    "compressed",
    "saturated",
    "reverbed",
    "distorted",
    "lofi",
    "lo-fi",
)

_TAG = re.compile(r"\[([^\]]*)\]")


@dataclass(frozen=True, slots=True)
class Violation:
    """One broken rule, with where it broke."""

    rule: str
    detail: str
    line: int | None = None


@dataclass(slots=True)
class Validation:
    """The verdict on one prompt."""

    violations: list[Violation]

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def reasons(self) -> list[str]:
        return [violation.rule for violation in self.violations]


def descriptors(description: str) -> list[str]:
    """The comma separated descriptors of a Description, trimmed and in order."""
    return [part.strip() for part in description.split(",") if part.strip()]


def instrument_noun(instrument: str) -> str:
    """The word a Structure modifier would use: the last word of the phrase.

    ``twangy reverb guitar`` is written in Description with its adjectives, and appears
    in Structure as ``guitar``, because a section is not the place for a production
    adjective.
    """
    words = instrument.strip().split()
    return words[-1].lower() if words else ""


def validate_description(description: str, config: AutocutConfig) -> list[Violation]:
    """Every Description rule from the spec, checked in the order a reader would."""
    found: list[Violation] = []
    limit = config.soundtrack.description_max_chars
    if len(description) > limit:
        found.append(
            Violation(
                rule="description_too_long",
                detail=f"{len(description)} characters, the limit is {limit}",
            )
        )
    parts = descriptors(description)
    if len(parts) < MIN_DESCRIPTORS or len(parts) > MAX_DESCRIPTORS:
        found.append(
            Violation(
                rule="description_descriptor_count",
                detail=f"{len(parts)} descriptors, wanted {MIN_DESCRIPTORS} to {MAX_DESCRIPTORS}",
            )
        )
    if ". " in description or description.strip().endswith("."):
        found.append(
            Violation(rule="description_sentence", detail="a full stop makes it a sentence")
        )
    for part in parts:
        if len(part.split()) > MAX_DESCRIPTOR_WORDS:
            found.append(
                Violation(
                    rule="description_sentence",
                    detail=f"{part!r} is {len(part.split())} words, a descriptor not a phrase",
                )
            )
    lowered = [part.lower() for part in parts]
    repeated = {part for part in lowered if lowered.count(part) > 1}
    if repeated:
        found.append(
            Violation(
                rule="description_repeated",
                detail="repeated: " + ", ".join(sorted(repeated)),
            )
        )
    if lowered[-2:] != list(INSTRUMENTAL_SUFFIX):
        found.append(
            Violation(
                rule="missing_instrumental",
                detail="must end with 'no vocals, instrumental'",
            )
        )
    return found


def validate_structure(
    structure: list[str], config: AutocutConfig, instruments: tuple[str, ...] = ()
) -> list[Violation]:
    """Every Structure rule from the spec. Line numbers are 1 based within the block."""
    found: list[Violation] = []
    allowed = {section.lower() for section in config.soundtrack.allowed_sections}
    modifiers: list[str] = []
    per_section: dict[str, int] = {}

    for number, raw in enumerate(structure, start=1):
        line = raw.strip()
        tags = _TAG.findall(line)
        if len(tags) != 1 or _TAG.sub("", line).strip():
            found.append(
                Violation(
                    rule="multiple_tags_on_line",
                    detail=f"{line!r} is not exactly one bracketed tag",
                    line=number,
                )
            )
            continue
        inside = tags[0]
        if "," in inside:
            found.append(
                Violation(
                    rule="comma_in_tag",
                    detail=f"{line!r} puts two ideas in one tag",
                    line=number,
                )
            )
            continue
        words = inside.split()
        if not words:
            found.append(Violation(rule="unknown_section", detail="empty tag", line=number))
            continue

        # The section word may be two words, as in "verse 1" and "pre-chorus".
        section = words[-1].lower()
        if len(words) >= 2 and f"{words[-2].lower()} {section}" in allowed:
            section = f"{words[-2].lower()} {section}"
            modifier_words = words[:-2]
        else:
            modifier_words = words[:-1]

        # Checked before the section word, because a tag asking for a voice is a vocal
        # tag whatever it calls its section. Reporting "unknown_section" for
        # "[soft vocals]" would send the reader looking for the right word for vocals.
        if any(vocal in inside.lower() for vocal in VOCAL_WORDS):
            found.append(
                Violation(rule="vocal_tag", detail=f"{inside!r} asks for a voice", line=number)
            )
            continue
        if section not in allowed:
            found.append(
                Violation(
                    rule="unknown_section",
                    detail=f"{section!r} is not an allowed section word",
                    line=number,
                )
            )
            continue
        if len(modifier_words) > 1:
            found.append(
                Violation(
                    rule="too_many_modifiers",
                    detail=f"{inside!r} has {len(modifier_words)} modifiers, one is allowed",
                    line=number,
                )
            )
        for word in modifier_words:
            if word.lower() in PRODUCTION_WORDS:
                found.append(
                    Violation(
                        rule="production_modifier",
                        detail=f"{word!r} describes a sound, so it belongs in Description",
                        line=number,
                    )
                )
        modifiers.extend(word.lower() for word in modifier_words)
        if section != "end":
            per_section[section] = per_section.get(section, 0) + 1

    for section, count in per_section.items():
        if count < MIN_SECTION_TAGS or count > MAX_SECTION_TAGS:
            found.append(
                Violation(
                    rule="section_tag_count",
                    detail=(
                        f"{section!r} has {count} tags, wanted "
                        f"{MIN_SECTION_TAGS} to {MAX_SECTION_TAGS}"
                    ),
                )
            )

    for instrument in instruments:
        noun = instrument_noun(instrument)
        if not noun:
            continue
        seen = sum(1 for word in modifiers if word == noun)
        if seen < 2:
            found.append(
                Violation(
                    rule="instrument_coverage",
                    detail=f"{noun!r} from Description appears {seen} times, wanted at least 2",
                )
            )

    if not structure or structure[-1].strip().lower() != "[end]":
        found.append(
            Violation(
                rule="missing_end",
                detail="the last line must be '[end]'",
                line=len(structure) or None,
            )
        )
    return found


def validate_prompt(
    description: str,
    structure: list[str],
    config: AutocutConfig,
    instruments: tuple[str, ...] = (),
) -> Validation:
    """Both blocks at once, which is how a prompt is ever used."""
    return Validation(
        violations=validate_description(description, config)
        + validate_structure(structure, config, instruments)
    )

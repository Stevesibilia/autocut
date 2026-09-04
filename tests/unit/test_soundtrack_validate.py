"""The malformed prompt battery from specs/prompt-validation, plus a valid prompt.

Each test breaks exactly one rule, because the point of the validator is that it names
the rule that broke. A test that breaks two cannot tell whether the second was noticed.
"""

from __future__ import annotations

import pytest

from autocut.core.config import AutocutConfig
from autocut.core.soundtrack.validate import (
    descriptors,
    instrument_noun,
    validate_description,
    validate_prompt,
    validate_structure,
)

GOOD_DESCRIPTION = (
    "surf rock, twangy reverb guitar, driving drums, sunny, 128 bpm, no vocals, instrumental"
)

GOOD_STRUCTURE = [
    "[sparse intro]",
    "[guitar intro]",
    "[sunny intro]",
    "[steady verse]",
    "[drums verse]",
    "[sunny verse]",
    "[driving drop]",
    "[guitar drop]",
    "[drums drop]",
    "[fading outro]",
    "[guitar outro]",
    "[drums outro]",
    "[end]",
]

INSTRUMENTS = ("twangy reverb guitar", "driving drums")


@pytest.fixture
def config() -> AutocutConfig:
    return AutocutConfig()


def reasons(description: str, structure: list[str], config: AutocutConfig) -> list[str]:
    return validate_prompt(description, structure, config, INSTRUMENTS).reasons


def test_a_valid_prompt_passes(config: AutocutConfig) -> None:
    result = validate_prompt(GOOD_DESCRIPTION, GOOD_STRUCTURE, config, INSTRUMENTS)

    assert result.ok
    assert result.violations == []
    assert result.reasons == []


def test_a_description_of_240_characters_is_too_long(config: AutocutConfig) -> None:
    padded = "surf rock, " + "x" * 220 + ", sunny, no vocals, instrumental"
    assert len(padded) > 240

    assert "description_too_long" in reasons(padded, GOOD_STRUCTURE, config)


def test_the_length_limit_comes_from_configuration(config: AutocutConfig) -> None:
    config.soundtrack.description_max_chars = 40

    assert "description_too_long" in reasons(GOOD_DESCRIPTION, GOOD_STRUCTURE, config)


def test_three_descriptors_are_too_few(config: AutocutConfig) -> None:
    assert "description_descriptor_count" in reasons(
        "surf rock, no vocals, instrumental", GOOD_STRUCTURE, config
    )


def test_eight_descriptors_are_too_many(config: AutocutConfig) -> None:
    long = (
        "surf rock, twangy guitar, driving drums, warm bass, sunny, bright, 128 bpm, "
        "no vocals, instrumental"
    )
    assert "description_descriptor_count" in reasons(long, GOOD_STRUCTURE, config)


def test_a_sentence_is_not_a_description(config: AutocutConfig) -> None:
    prose = "surf rock with reverb. bright and sunny, 128 bpm, no vocals, instrumental"

    assert "description_sentence" in reasons(prose, GOOD_STRUCTURE, config)


def test_a_descriptor_of_more_than_five_words_is_a_phrase(config: AutocutConfig) -> None:
    wordy = (
        "surf rock, a guitar that rings out across the bay, sunny, 128 bpm, no vocals, instrumental"
    )
    assert "description_sentence" in reasons(wordy, GOOD_STRUCTURE, config)


def test_a_repeated_descriptor_is_rejected(config: AutocutConfig) -> None:
    repeated = "surf rock, sunny, driving drums, sunny, 128 bpm, no vocals, instrumental"

    assert "description_repeated" in reasons(repeated, GOOD_STRUCTURE, config)


def test_a_description_ending_in_the_bpm_is_missing_the_marker(config: AutocutConfig) -> None:
    """The scenario from the spec: it has to end with 'no vocals, instrumental'."""
    ending = "surf rock, twangy guitar, driving drums, sunny, 120 bpm"

    assert "missing_instrumental" in reasons(ending, GOOD_STRUCTURE, config)


def test_the_marker_has_to_be_last_not_merely_present(config: AutocutConfig) -> None:
    misplaced = "surf rock, no vocals, instrumental, twangy guitar, driving drums, sunny"

    assert "missing_instrumental" in reasons(misplaced, GOOD_STRUCTURE, config)


def test_two_tags_on_one_line(config: AutocutConfig) -> None:
    structure = [*GOOD_STRUCTURE[:3], "[warm verse] [soft verse]", *GOOD_STRUCTURE[3:]]

    found = validate_structure(structure, config, INSTRUMENTS)
    assert "multiple_tags_on_line" in [violation.rule for violation in found]


def test_text_outside_the_brackets(config: AutocutConfig) -> None:
    structure = [*GOOD_STRUCTURE[:3], "then [warm verse]", *GOOD_STRUCTURE[3:]]

    assert "multiple_tags_on_line" in [v.rule for v in validate_structure(structure, config)]


def test_a_comma_inside_the_brackets(config: AutocutConfig) -> None:
    """The scenario from the spec: '[slow, dark intro]' is two ideas in one tag."""
    structure = [
        "[sparse intro]",
        "[guitar intro]",
        "[slow, dark intro]",
        *GOOD_STRUCTURE[3:],
    ]
    found = validate_structure(structure, config, INSTRUMENTS)

    comma = [violation for violation in found if violation.rule == "comma_in_tag"]
    assert comma
    assert comma[0].line == 3


def test_two_modifiers_before_the_section_word(config: AutocutConfig) -> None:
    structure = ["[slow dark sparse intro]", *GOOD_STRUCTURE[1:]]

    assert "too_many_modifiers" in [v.rule for v in validate_structure(structure, config)]


def test_an_invented_section_word(config: AutocutConfig) -> None:
    """The scenario from the spec: '[epic climax]' is not a Suno section."""
    structure = [*GOOD_STRUCTURE[:6], "[epic climax]", *GOOD_STRUCTURE[6:]]
    found = validate_structure(structure, config, INSTRUMENTS)

    unknown = [violation for violation in found if violation.rule == "unknown_section"]
    assert unknown
    assert unknown[0].line == 7


def test_a_two_word_section_is_allowed(config: AutocutConfig) -> None:
    """'verse 1' and 'pre-chorus' are single sections whose word has a space in it."""
    structure = [
        "[sparse intro]",
        "[guitar intro]",
        "[sunny intro]",
        "[steady verse 1]",
        "[drums verse 1]",
        "[sunny verse 1]",
        "[driving drop]",
        "[guitar drop]",
        "[drums drop]",
        "[end]",
    ]
    found = validate_structure(structure, config, INSTRUMENTS)

    assert [violation.rule for violation in found] == []


def test_two_tags_in_a_section_are_too_few(config: AutocutConfig) -> None:
    structure = ["[sparse intro]", "[guitar intro]", *GOOD_STRUCTURE[3:]]

    assert "section_tag_count" in [v.rule for v in validate_structure(structure, config)]


def test_seven_tags_in_a_section_are_too_many(config: AutocutConfig) -> None:
    structure = [
        *[
            f"[{word} intro]"
            for word in ("sparse", "slow", "gentle", "warm", "soft", "open", "airy")
        ],
        "[end]",
    ]
    assert "section_tag_count" in [v.rule for v in validate_structure(structure, config)]


@pytest.mark.parametrize(
    "vocal", ["[soft vocals]", "[warm choir]", "[fast rap]", "[bright singing]"]
)
def test_a_vocal_tag_is_rejected(config: AutocutConfig, vocal: str) -> None:
    structure = [*GOOD_STRUCTURE[:3], vocal, *GOOD_STRUCTURE[3:]]

    assert "vocal_tag" in [v.rule for v in validate_structure(structure, config)]


@pytest.mark.parametrize("word", ["filtered", "sidechained", "punchy"])
def test_a_production_adjective_belongs_in_the_description(
    config: AutocutConfig, word: str
) -> None:
    structure = [f"[{word} intro]", *GOOD_STRUCTURE[1:]]

    assert "production_modifier" in [v.rule for v in validate_structure(structure, config)]


def test_an_instrument_named_once_is_not_covered(config: AutocutConfig) -> None:
    structure = [
        "[sparse intro]",
        "[guitar intro]",
        "[sunny intro]",
        "[steady verse]",
        "[sunny verse]",
        "[open verse]",
        "[fading outro]",
        "[sunny outro]",
        "[calm outro]",
        "[end]",
    ]
    found = validate_structure(structure, config, INSTRUMENTS)

    coverage = [v for v in found if v.rule == "instrument_coverage"]
    assert {v.detail.split("'")[1] for v in coverage} == {"guitar", "drums"}


def test_an_instrument_the_description_does_not_name_needs_no_coverage(
    config: AutocutConfig,
) -> None:
    named = validate_structure(GOOD_STRUCTURE, config, ("warm bass",))
    assert "instrument_coverage" in [violation.rule for violation in named]

    # With no instruments declared there is nothing to cover, and the same structure
    # passes.
    assert validate_structure(GOOD_STRUCTURE, config, ()) == []


def test_an_outro_as_the_last_line_is_missing_the_end(config: AutocutConfig) -> None:
    """The scenario from the spec: the last line is always '[end]'."""
    structure = GOOD_STRUCTURE[:-1]

    assert "missing_end" in [v.rule for v in validate_structure(structure, config)]


def test_every_violation_is_returned_with_its_line(config: AutocutConfig) -> None:
    """The scenario from the spec: a comma on line 4 and no end, both reported."""
    structure = [
        "[sparse intro]",
        "[guitar intro]",
        "[sunny intro]",
        "[slow, dark verse]",
        "[drums verse]",
        "[sunny verse]",
        "[fading outro]",
        "[guitar outro]",
        "[drums outro]",
    ]
    found = validate_structure(structure, config, INSTRUMENTS)
    rules = [violation.rule for violation in found]

    assert "comma_in_tag" in rules
    assert "missing_end" in rules
    comma = next(v for v in found if v.rule == "comma_in_tag")
    assert comma.line == 4


def test_an_empty_structure_is_missing_the_end(config: AutocutConfig) -> None:
    assert "missing_end" in [v.rule for v in validate_structure([], config)]


def test_the_end_tag_is_not_counted_as_a_section(config: AutocutConfig) -> None:
    """One '[end]' would otherwise read as a section with one tag, which is too few."""
    found = validate_structure(GOOD_STRUCTURE, config, INSTRUMENTS)

    assert "section_tag_count" not in [violation.rule for violation in found]


def test_the_allowed_sections_come_from_configuration(config: AutocutConfig) -> None:
    config.soundtrack.allowed_sections = ["intro", "end"]

    found = validate_structure(GOOD_STRUCTURE, config, INSTRUMENTS)
    assert "unknown_section" in [violation.rule for violation in found]


def test_splitting_descriptors() -> None:
    assert descriptors("a, b ,  c") == ["a", "b", "c"]
    assert descriptors("") == []


def test_the_instrument_noun_is_the_last_word() -> None:
    assert instrument_noun("twangy reverb guitar") == "guitar"
    assert instrument_noun("Drums") == "drums"
    assert instrument_noun("  ") == ""


def test_a_description_alone_can_be_validated(config: AutocutConfig) -> None:
    assert validate_description(GOOD_DESCRIPTION, config) == []

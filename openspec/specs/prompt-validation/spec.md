# prompt-validation Specification

## Purpose
Prompt validation catches a malformed Suno prompt before a track is generated, because a wrong prompt produces wrong music and the error is invisible by eye.

## Requirements

### Requirement: Description rules

The validator SHALL reject a Description that exceeds `soundtrack.description_max_chars` (default 200), that has fewer than 4 or more than 7 comma separated descriptors, that contains a sentence (a period followed by a space, or more than five words in one descriptor), that repeats a descriptor, or that does not end with `no vocals, instrumental`.

#### Scenario: Too long

- **WHEN** a Description is 240 characters
- **THEN** validation fails with reason `description_too_long`

#### Scenario: Missing instrumental marker

- **WHEN** a Description ends with `120 bpm`
- **THEN** validation fails with reason `missing_instrumental`

### Requirement: Structure rules

The validator SHALL reject a Structure with more than one bracketed tag on a line, a comma inside brackets, more than one modifier before the section word, a section word outside the allowed list, fewer than 3 or more than 6 tags in any section, any vocal tag (`vocals`, `verse` with a lyric line, `choir`, `singing`, `rap`), a production adjective used as a structure modifier, an instrument named in Description that appears fewer than twice, or a last line other than `[end]`.

#### Scenario: Comma in brackets

- **WHEN** a line reads `[slow, dark intro]`
- **THEN** validation fails with reason `comma_in_tag`

#### Scenario: Invented section

- **WHEN** a line reads `[epic climax]`
- **THEN** validation fails with reason `unknown_section`

#### Scenario: Missing end

- **WHEN** the last line is `[outro]`
- **THEN** validation fails with reason `missing_end`

#### Scenario: Valid prompt

- **WHEN** a prompt follows every rule
- **THEN** validation passes with an empty reason list

### Requirement: Machine readable result

Validation SHALL return the full list of violated rules with line numbers, not only the first, so the GUI can mark each one.

#### Scenario: Two errors

- **WHEN** a prompt has a comma in a bracket on line 4 and no `[end]`
- **THEN** both reasons are returned with line 4 attached to the first

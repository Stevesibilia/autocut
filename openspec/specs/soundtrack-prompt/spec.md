# soundtrack-prompt Specification

## Purpose
The soundtrack prompt turns the selected edit into a Suno prompt that fits it: genre from what the footage shows, structure from how its energy moves, length and BPM from its durations.

## Requirements

### Requirement: Signals from the selected edit

The system SHALL derive from the selected segments, in order: total duration and clip count, an energy curve (mean motion per clip along the edit order, smoothed), the dominant tags and their share, up to five captions when present, the class mix, the dominant time of day from creation times, and up to three place names when available. Signals SHALL be stored on the manifest soundtrack block.

#### Scenario: Sardinia edit

- **WHEN** the edit is 29 clips of 76.5 s with 19 action cam, 9 drone and 1 phone, tags beach 15 and aerial 8, shot between 09:00 and 15:00
- **THEN** the signals record 76.5 s, 29 clips, class mix in those proportions, `beach` as the dominant tag, `daytime` as the time of day

### Requirement: Genre table

Genre selection SHALL come from `soundtrack.genres`, a list of rows each with a profile condition (dominant tags, class shares, energy band, time of day, any of which may be absent), a genre, two or three instruments with adjectives and a BPM range. The first row whose conditions all match wins; `soundtrack.default_profile` names the row used when none matches. The shipped rows cover: upbeat folk, indie pop, rock, surf rock, country, Americana, reggae and dub, funk and disco, pop punk, cinematic ambient and post-rock, acoustic and ukulele pop, Italian and Mediterranean folk.

#### Scenario: Beach day

- **WHEN** the dominant tag is `beach` with `underwater` present and energy is mid
- **THEN** the surf rock row matches and the prompt genre is surf rock

#### Scenario: Aerial afternoon

- **WHEN** drone clips are over half the edit and energy is low
- **THEN** the cinematic ambient row matches

#### Scenario: Nothing matches

- **WHEN** no row's conditions match
- **THEN** the default profile row (upbeat folk) is used and the report says so

### Requirement: Proposed BPM

The system SHALL propose a BPM inside the chosen row's range that minimizes the mean distance of the assigned clip durations to whole beats, rounded to an integer, and SHALL store it as `proposed_bpm`. `--bpm` overrides it.

#### Scenario: Durations near two seconds

- **WHEN** most clips last about 2.0 s and the range is 100 to 130
- **THEN** a BPM near 120 is proposed, where 2.0 s is four beats

### Requirement: Prompt blocks

The system SHALL write Title, Description and Structure blocks. Description SHALL be comma separated tags in the order genre or era, instruments with adjectives, mood, production, BPM, 4 to 7 descriptors, no repeated concept, ending with `no vocals, instrumental`, within 200 characters. Structure SHALL be one bracketed tag per line, one modifier per tag, section words from the allowed list, 3 to 6 tags per section, every instrument from Description appearing in at least two tags, no vocal tags, last line `[end]`. The structure arc SHALL follow the energy curve: calm opening, development, a peak aligned with the highest energy clips, resolution.

#### Scenario: Peak placement

- **WHEN** the energy curve peaks in the last third of the edit
- **THEN** the `[drop]` or `[chorus]` section falls in the last third of the Structure

#### Scenario: Instrument coverage

- **WHEN** Description names `twangy guitar` and `driving drums`
- **THEN** Structure contains `guitar` and `drums` as modifiers at least twice each

### Requirement: Variants and output file

The system SHALL generate `soundtrack.variants` prompts (default 3) that differ in mood or instrumentation while sharing genre and BPM, validate each, and write them to `suno-prompt.md` with copy-ready blocks and the proposed BPM. Invalid variants MUST be regenerated or dropped, never written.

#### Scenario: Three variants

- **WHEN** `autocut soundtrack` runs with defaults
- **THEN** `suno-prompt.md` contains three valid variants and the manifest lists them

### Requirement: Optional refinement

When cloud is enabled per the cloud providers gate and `soundtrack.refine` is true, the system SHALL send the structured signals and the template prompt to the text model and use its answer only if it passes validation, otherwise keep the template prompt and record the rejection.

#### Scenario: Refined prompt fails validation

- **WHEN** the model returns a Structure with a comma inside a bracket
- **THEN** the template prompt is kept and the manifest records `refinement: rejected`

### Requirement: Command

`autocut soundtrack <project>` SHALL run on a selected project with `--variants`, `--bpm` and `--genre` overrides, and `autocut run` SHALL call it after select.

#### Scenario: Not selected yet

- **WHEN** the project has no selected segments
- **THEN** the command exits non-zero saying to run select first

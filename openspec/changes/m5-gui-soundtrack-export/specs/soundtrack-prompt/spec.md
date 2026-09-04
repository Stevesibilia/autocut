## MODIFIED Requirements

### Requirement: Variants and output file

The system SHALL generate `soundtrack.variants` prompts (default 3) that differ in mood or instrumentation while sharing genre and BPM, validate each, and write them to `suno-prompt.md` with copy-ready blocks and the proposed BPM. Invalid variants MUST be regenerated or dropped, never written. Mood controls (calmer to more energetic, cinematic to intimate) SHALL select alternates within the matched row and regenerate without changing the genre. A hand-edited prompt that passes validation MAY be stored as the chosen variant with source `user` and SHALL then be the first block in `suno-prompt.md`.

#### Scenario: Three variants

- **WHEN** `autocut soundtrack` runs with defaults
- **THEN** `suno-prompt.md` contains three valid variants and the manifest lists them

#### Scenario: User variant first

- **WHEN** a valid hand-edited prompt is stored
- **THEN** `suno-prompt.md` opens with it, marked as the user's, followed by the generated variants

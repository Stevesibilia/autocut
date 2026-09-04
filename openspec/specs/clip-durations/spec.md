# clip-durations Specification

## Purpose

Clip durations give the edit rhythm without music: each selected clip gets a length that fits its content, its quality and its neighbours, within bounds the user controls.

## Requirements

### Requirement: Base duration by class scaled by score

For each selected clip the system SHALL start from `selection.duration_by_class` for its source class (defaults drone 4.0, actioncam 2.0, phone 2.5, reflex 3.0, generic 3.0), multiply it by a factor that grows linearly with the clip's score across `selection.score_duration_range` (default 0.8 to 1.2, so a score of 0 gives 0.8x and a score of 1 gives 1.2x), and clamp the result to `selection.duration_min_seconds` and `selection.duration_max_seconds` (defaults 1.5 and 6.0) and to the clip's trimmed span.

#### Scenario: Strong drone clip

- **WHEN** a drone clip has score 1.0 with the default configuration
- **THEN** its target duration is 4.8 s

#### Scenario: Weak action cam clip

- **WHEN** an action cam clip has score 0.0
- **THEN** its target duration is 1.6 s

#### Scenario: Segment shorter than target

- **WHEN** a phone clip's trimmed span lasts 1.4 s and the computed duration is 2.5 s
- **THEN** its target duration is 1.4 s with reason `clamped`

### Requirement: Hero shots

The top `selection.hero_share` (default 0.1) of selected clips by score SHALL have their duration multiplied by `selection.hero_multiplier` (default 1.5) before clamping and SHALL record reason `hero`.

#### Scenario: Four heroes in forty

- **WHEN** 40 clips are selected with the default share
- **THEN** the 4 highest scoring clips carry reason `hero` and durations 1.5x their base result, within the maximum

### Requirement: Long and short alternation

When `selection.alternate_durations` is true (default), the system SHALL walk the selected clips in chronological order and, wherever three consecutive clips fall in the same bucket (long when at or above the class base, short when below), SHALL move the middle clip to the other bucket by scaling it 25 percent, within the clamps and its trimmed span, recording reason `alternation`. Hero clips MUST NOT be shortened by alternation.

#### Scenario: Three long in a row

- **WHEN** three consecutive selected clips are all at or above their class base and none is a hero
- **THEN** the middle one is shortened by 25 percent and records `alternation`

#### Scenario: Hero protected

- **WHEN** the middle clip of three long ones is a hero
- **THEN** the third clip is shortened instead

### Requirement: Total duration target

When `selection.target_total_seconds` is set, the system SHALL scale every duration by the same factor so the sum lands within 5 percent of the target, re-clamping each clip and recording reason `total` on clips that changed, and SHALL report the achieved total. When the target cannot be reached within the clamps the system SHALL report the shortfall rather than violate the bounds.

#### Scenario: Ninety second edit

- **WHEN** 40 clips sum to 120 s and the target is 90 s
- **THEN** every clip is scaled by 0.75 within its clamps and the reported total is between 85.5 and 94.5 s

### Requirement: Uniform override

When `autocut select --duration <seconds>` is given, every selected clip SHALL receive that duration, clamped to its trimmed span, with reason `override`, and no scaling, hero or alternation SHALL apply.

#### Scenario: Legacy behavior

- **WHEN** `--duration 3.0` is passed
- **THEN** every clip whose span allows it has target duration 3.0 and reason `override`

### Requirement: Recorded and reported

Each selected segment SHALL carry `duration_reason` and the manifest selection block SHALL record the total duration of the edit. `autocut select` SHALL print the total duration and the count of clips per bucket. When beat sync has run, the segment SHALL also carry final bounds and the number of beats, `duration_reason` SHALL read `beat`, and the report SHALL show the beat count next to the duration.

#### Scenario: Summary line

- **WHEN** selection completes
- **THEN** the CLI prints the total seconds and how many clips are long, short and hero

#### Scenario: After sync

- **WHEN** beat sync has run at 120 BPM and a clip got four beats
- **THEN** its card shows `2.0 s, 4 beats` and reason `beat`

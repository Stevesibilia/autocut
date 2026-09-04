## MODIFIED Requirements

### Requirement: Recorded and reported

Each selected segment SHALL carry `duration_reason` and the manifest selection block SHALL record the total duration of the edit. `autocut select` SHALL print the total duration and the count of clips per bucket. When beat sync has run, the segment SHALL also carry final bounds and the number of beats, `duration_reason` SHALL read `beat`, and the report SHALL show the beat count next to the duration.

#### Scenario: Summary line

- **WHEN** selection completes
- **THEN** the CLI prints the total seconds and how many clips are long, short and hero

#### Scenario: After sync

- **WHEN** beat sync has run at 120 BPM and a clip got four beats
- **THEN** its card shows `2.0 s, 4 beats` and reason `beat`

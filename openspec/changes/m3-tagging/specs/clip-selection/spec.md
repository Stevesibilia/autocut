## MODIFIED Requirements

### Requirement: Caps and quotas

Selection SHALL stop at `selection.max_clips`. It SHALL select at most `selection.max_clips_per_file` for the candidate's class from one source file, at most `selection.max_clips_per_cluster` from one visual cluster, and SHALL ensure each class reaches at least `selection.min_share_per_class` of the final count when enough candidates of that class exist, by reserving slots for under-represented classes before filling the rest by penalized score. When tags exist, it SHALL select at most `selection.max_share_per_tag` of the final count with the same dominant tag while eligible candidates with a different dominant tag or no tag remain; the cap is lifted only when nothing else is eligible.

#### Scenario: Per-file cap

- **WHEN** a drone file has three candidates scoring 0.9, 0.8, 0.7 and the drone cap is 1
- **THEN** only the 0.9 candidate is selected from that file

#### Scenario: Class share

- **WHEN** `min_share_per_class.phone` is 0.2, max clips is 10, and phone candidates score below every drone candidate
- **THEN** at least 2 phone clips are selected

#### Scenario: Not enough candidates for the share

- **WHEN** a class share requires 3 clips and the class has 1 eligible candidate
- **THEN** that one is selected and the remaining slots go to other classes

#### Scenario: Tag share cap

- **WHEN** `max_share_per_tag` is 0.5, max clips is 10, and twelve eligible candidates are tagged `beach` and four `food`
- **THEN** at most 5 beach clips are selected while food candidates remain

#### Scenario: Only one tag available

- **WHEN** every eligible candidate carries the same dominant tag
- **THEN** the cap is lifted and selection fills to max clips

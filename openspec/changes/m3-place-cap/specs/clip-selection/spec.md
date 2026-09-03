## MODIFIED Requirements

### Requirement: Caps and quotas

Selection SHALL stop at `selection.max_clips`, itself bounded to `selection.max_candidate_share` (default 0.5) of the eligible candidates rounded up unless `--max-clips` was given explicitly. It SHALL select at most `selection.max_clips_per_file` for the candidate's class from one source file, at most `selection.max_clips_per_cluster` from one visual cluster, at most `selection.max_clips_per_place` (default 3) from one place visit while eligible candidates outside that visit remain, and SHALL ensure each class reaches at least `selection.min_share_per_class` of the final count when enough candidates of that class exist, by reserving slots for under-represented classes before filling the rest by penalized score. A candidate held back by the place cap SHALL stay `candidate` with reason `place_cap` and record the selected clips that filled its visit in `held_by`.

#### Scenario: Per-file cap

- **WHEN** a drone file has three candidates scoring 0.9, 0.8, 0.7 and the drone cap is 1
- **THEN** only the 0.9 candidate is selected from that file

#### Scenario: Class share

- **WHEN** `min_share_per_class.phone` is 0.2, max clips is 10, and phone candidates score below every drone candidate
- **THEN** at least 2 phone clips are selected

#### Scenario: Not enough candidates for the share

- **WHEN** a class share requires 3 clips and the class has 1 eligible candidate
- **THEN** that one is selected and the remaining slots go to other classes

#### Scenario: Five shots, one visit

- **WHEN** five candidates from five files share one visit, the place cap is 3 and other eligible candidates exist
- **THEN** the three with the highest penalized score are selected and the other two stay `candidate` with reason `place_cap` naming those three

#### Scenario: Place cap lifted last

- **WHEN** every remaining eligible candidate belongs to a visit that already has 3 selected clips and slots remain
- **THEN** the cap is lifted and selection fills to max clips

#### Scenario: Candidate share ceiling

- **WHEN** 60 candidates are eligible, `max_clips` is 40 and `max_candidate_share` is 0.5 with no `--max-clips` flag
- **THEN** at most 30 clips are selected and the CLI says the ceiling applied

#### Scenario: Explicit flag wins

- **WHEN** `--max-clips 40` is passed on the same folder
- **THEN** 40 clips are selected

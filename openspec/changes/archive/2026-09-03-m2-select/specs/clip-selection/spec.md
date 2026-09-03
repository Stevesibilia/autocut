## Purpose

Clip selection chooses the final ordered set of clips from the scored candidates, balancing quality against diversity and honoring per-file, per-class and total caps.

## ADDED Requirements

### Requirement: Greedy selection with similarity penalty

The system SHALL select candidates iteratively, at each step picking the candidate that maximizes `score - lambda * max(similarity to already selected)` among those still eligible, where `lambda` is `selection.diversity_lambda`. Rejected segments MUST never be eligible.

#### Scenario: Near duplicates

- **WHEN** two candidates have scores 0.9 and 0.85, similarity 0.9 to each other, and a third has score 0.6 and similarity 0.1 to both, with lambda 0.6 and max clips 2
- **THEN** the selection is the 0.9 candidate and the 0.6 candidate

#### Scenario: Lambda zero

- **WHEN** lambda is 0
- **THEN** selection is by score alone subject to the caps

### Requirement: Caps and quotas

Selection SHALL stop at `selection.max_clips`. It SHALL select at most `selection.max_clips_per_file` for the candidate's class from one source file, at most `selection.max_clips_per_cluster` from one visual cluster, and SHALL ensure each class reaches at least `selection.min_share_per_class` of the final count when enough candidates of that class exist, by reserving slots for under-represented classes before filling the rest by penalized score.

#### Scenario: Per-file cap

- **WHEN** a drone file has three candidates scoring 0.9, 0.8, 0.7 and the drone cap is 1
- **THEN** only the 0.9 candidate is selected from that file

#### Scenario: Class share

- **WHEN** `min_share_per_class.phone` is 0.2, max clips is 10, and phone candidates score below every drone candidate
- **THEN** at least 2 phone clips are selected

#### Scenario: Not enough candidates for the share

- **WHEN** a class share requires 3 clips and the class has 1 eligible candidate
- **THEN** that one is selected and the remaining slots go to other classes

### Requirement: Minimum temporal gap

Two selected clips that are adjacent in the final chronological order SHALL be at least `selection.min_temporal_gap_seconds` apart in absolute time unless no other eligible candidate remains.

#### Scenario: Same minute

- **WHEN** two high scoring candidates are 20 seconds apart and the gap is 60 seconds
- **THEN** the second is skipped while other eligible candidates exist

### Requirement: Outcome and order

Selected segments SHALL have outcome `selected` and an `order` starting at 1 following absolute time (file creation time plus best window center). Eligible candidates that were not selected SHALL stay `candidate`, and when a candidate lost to a near duplicate the id of the selected duplicate SHALL be recorded as `lost_to`.

#### Scenario: Ordering across devices

- **WHEN** a phone clip at 13:39, a drone clip at 13:37 and an action cam clip at 13:38 are selected
- **THEN** their orders are 2, 1 and 3 respectively

### Requirement: Re-runnable select

`autocut select` SHALL reset every `selected` segment to `candidate`, clear `order` and `lost_to`, then select again with the current configuration and command line overrides. It MUST NOT change any `rejected` segment and MUST NOT decode video. The parameters used SHALL be recorded in the manifest.

#### Scenario: Twenty runs

- **WHEN** `autocut select` runs twice with different `--diversity`
- **THEN** the second run's selection reflects the new lambda and rejected segments are unchanged

### Requirement: Run shortcut

`autocut run <sources> --out <dir>` SHALL execute analyze, select and report in sequence with the same options and exit codes as the individual commands.

#### Scenario: One command

- **WHEN** `autocut run ./footage --out ./edit` completes
- **THEN** `manifest.json` has selected segments and `report.html` exists

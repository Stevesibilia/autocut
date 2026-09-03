## MODIFIED Requirements

### Requirement: Greedy selection with similarity penalty

The system SHALL select candidates iteratively, at each step picking the candidate that maximizes `score - lambda * max(similarity to already selected)` among those still eligible, where `lambda` is `selection.diversity_lambda`. Rejected segments MUST never be eligible. When `export.vertical_strategy` is `exclude`, segments of display-vertical files MUST NOT be eligible and SHALL be marked with reason `vertical` while keeping outcome `candidate`, so the report shows them as excluded by policy rather than rejected on quality.

#### Scenario: Near duplicates

- **WHEN** two candidates have scores 0.9 and 0.85, similarity 0.9 to each other, and a third has score 0.6 and similarity 0.1 to both, with lambda 0.6 and max clips 2
- **THEN** the selection is the 0.9 candidate and the 0.6 candidate

#### Scenario: Lambda zero

- **WHEN** lambda is 0
- **THEN** selection is by score alone subject to the caps

#### Scenario: Vertical excluded by policy

- **WHEN** a display-vertical phone candidate has the highest score and the vertical strategy is `exclude`
- **THEN** it is not selected, stays `candidate` with reason `vertical`, and the report shows it as excluded

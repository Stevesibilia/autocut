## MODIFIED Requirements

### Requirement: Re-runnable select

`autocut select` SHALL reset every `selected` segment to `candidate`, clear `order` and `lost_to`, then select again with the current configuration and command line overrides. It MUST NOT change any `rejected` segment and MUST NOT decode video. Segments with user decision `keep` SHALL be selected first, before class shares and the greedy loop, and segments with user decision `reject` SHALL be ineligible. The parameters used SHALL be recorded in the manifest.

#### Scenario: Twenty runs

- **WHEN** `autocut select` runs twice with different `--diversity`
- **THEN** the second run's selection reflects the new lambda and rejected segments are unchanged

#### Scenario: Pins first

- **WHEN** three segments are kept by the user and max clips is 10
- **THEN** those three are selected and seven slots are filled by the normal rules

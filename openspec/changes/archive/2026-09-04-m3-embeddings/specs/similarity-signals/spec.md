## MODIFIED Requirements

### Requirement: Combined similarity in 0 to 1

The system SHALL compute a pairwise similarity between candidates in 0 to 1 as the weighted mean of the enabled signals, each in 0 to 1, with weights from configuration. A signal that cannot be computed for a pair (missing GPS, missing telemetry, missing embedding) SHALL be excluded from that pair's mean rather than counted as zero. When both candidates have an embedding and the semantic signal is enabled, the visual hash signal SHALL be excluded for that pair so the two visual signals are not double counted.

#### Scenario: Missing GPS

- **WHEN** two candidates have no GPS and only the visual and temporal signals are enabled
- **THEN** their similarity is the weighted mean of the visual and temporal signals only

#### Scenario: All signals disabled

- **WHEN** every signal is disabled in configuration
- **THEN** every pair has similarity 0 and selection degrades to pure score ranking

#### Scenario: Semantic replaces the hash

- **WHEN** both candidates have embeddings and the semantic signal is enabled
- **THEN** the pair's similarity uses the semantic signal and not the hash signal

#### Scenario: One embedding missing

- **WHEN** one candidate of a pair has no embedding
- **THEN** the pair falls back to the hash signal

## ADDED Requirements

### Requirement: Semantic signal

The semantic signal SHALL be the cosine similarity between the two candidates' embeddings mapped linearly from the range [`similarity.semantic_floor`, 1] onto 0 to 1 and clamped, with a default floor of 0.5, so unrelated scenes sit near 0 and the same scene from another angle sits above 0.7.

#### Scenario: Same bay, two angles

- **WHEN** two candidates show the same bay from different angles with cosine similarity 0.88 and a floor of 0.5
- **THEN** the semantic signal is 0.76

#### Scenario: Sunset and dinner

- **WHEN** two candidates have cosine similarity 0.45
- **THEN** the semantic signal is 0

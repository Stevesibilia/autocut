# similarity-signals Specification

## Purpose

Similarity signals estimate how alike two candidates are from data already in the cache, so selection can avoid near duplicates without any model.

## Requirements

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

### Requirement: Visual signal from hash and histogram

The visual fallback signal SHALL combine a perceptual hash distance and a color histogram distance computed on the segment's cached thumbnail frame. Two frames of the same scene from slightly different angles MUST score above 0.7, and two frames of unrelated scenes MUST score below 0.4.

#### Scenario: Same beach

- **WHEN** two thumbnails show the same beach panned by a few degrees
- **THEN** the visual signal is above 0.7

#### Scenario: Beach and dinner

- **WHEN** one thumbnail is a beach and the other an indoor dinner table
- **THEN** the visual signal is below 0.4

### Requirement: Spatial signal

The spatial signal SHALL map GPS distance between the two candidates onto 1 at zero meters and 0 at or beyond `similarity.spatial_radius_m`, linearly.

#### Scenario: Same spot

- **WHEN** two candidates are 10 meters apart with a radius of 200 meters
- **THEN** the spatial signal is 0.95

### Requirement: Temporal signal

The temporal signal SHALL map the distance between the two candidates' absolute timestamps (file creation time plus window offset) onto 1 at zero seconds and 0 at or beyond `similarity.temporal_radius_s`, linearly.

#### Scenario: Consecutive shots

- **WHEN** two candidates are 30 seconds apart with a radius of 600 seconds
- **THEN** the temporal signal is 0.95

### Requirement: Motion profile signal

The motion signal SHALL be the normalized correlation of the two candidates' per-frame motion series over their best windows, mapped to 0 to 1, so two identical pans score near 1.

#### Scenario: Two identical pans

- **WHEN** two candidates have the same motion series shape
- **THEN** the motion signal is above 0.9

### Requirement: Visual clusters

The system SHALL assign a `cluster_id` to candidates by single linkage over combined similarity above `selection.cluster_threshold`, so the report can group near duplicates.

#### Scenario: Three similar shots

- **WHEN** three candidates have pairwise similarity above the threshold with each other and below it with everything else
- **THEN** the three share one `cluster_id` and nobody else has it

### Requirement: Semantic signal

The semantic signal SHALL be the cosine similarity between the two candidates' embeddings mapped linearly from the range [`similarity.semantic_floor`, 1] onto 0 to 1 and clamped, with a default floor of 0.5, so unrelated scenes sit near 0 and the same scene from another angle sits above 0.7.

#### Scenario: Same bay, two angles

- **WHEN** two candidates show the same bay from different angles with cosine similarity 0.88 and a floor of 0.5
- **THEN** the semantic signal is 0.76

#### Scenario: Sunset and dinner

- **WHEN** two candidates have cosine similarity 0.45
- **THEN** the semantic signal is 0

## ADDED Requirements

### Requirement: Local aesthetic score

When `providers.aesthetic` is on and the `ai` extra is installed, every segment SHALL receive `Metrics.aesthetic` from the bundled LAION aesthetic head applied to its cached thumbnail, embedded with the OpenAI ViT-B/32 CLIP tower, as a 1 to 10 rating scaled to 0 to 1, with `aesthetic_source` set to `local`. The per-shot ratings SHALL be cached with the model id and reused while it matches. A cloud value SHALL never be overwritten by a local one. When `weights.aesthetic` is above 0 and any value changed, segment scores SHALL be recomputed. When the feature is off, local values SHALL be removed and no tower SHALL load.

#### Scenario: Local only

- **WHEN** a project is analysed with `providers.aesthetic` on and no cloud key
- **THEN** every segment with a cached thumbnail has an aesthetic between 0.1 and 1.0 marked `local`

#### Scenario: Cloud wins

- **WHEN** a segment has a cloud aesthetic and the local stage runs again
- **THEN** its aesthetic and source are unchanged, and the stage counts it as kept from cloud

#### Scenario: Legacy manifest

- **WHEN** a manifest from before this change has an aesthetic with no source
- **THEN** the value is treated as a cloud value

#### Scenario: Cached ratings

- **WHEN** the stage runs twice on an unchanged project
- **THEN** the second run loads no model and reports every file from cache

#### Scenario: Turned off

- **WHEN** the stage runs with `providers.aesthetic` off on a project with local values
- **THEN** the local values are removed, cloud values stay, and no model loads

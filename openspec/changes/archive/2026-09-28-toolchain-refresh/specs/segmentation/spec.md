## ADDED Requirements

### Requirement: Validation detector is optional

The PySceneDetect shot detector, selected with `analysis.detector = "pyscenedetect"`, SHALL require the optional `scenedetect` extra. The default installation SHALL NOT include PySceneDetect. When that detector is selected without the extra, analysis SHALL fail with a message that names the extra and how to install it.

#### Scenario: Extra missing

- **WHEN** `analysis.detector` is `"pyscenedetect"` and PySceneDetect is not installed
- **THEN** shot detection fails with a message naming the `scenedetect` extra

#### Scenario: Default detector

- **WHEN** `analysis.detector` is left at its default
- **THEN** analysis runs without PySceneDetect installed

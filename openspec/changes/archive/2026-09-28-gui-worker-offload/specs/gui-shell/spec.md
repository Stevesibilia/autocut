## ADDED Requirements

### Requirement: Closing during a stage

Closing the window while a stage runs SHALL cancel the stage, keep the window open with a status message, and close the window once the stage has ended. The manifest SHALL be saved only after the worker has stopped writing it. Closing SHALL NOT block the UI thread while it waits. Closing a project SHALL report failure, and SHALL NOT save, when the stage does not stop within `gui.close_wait_ms`.

#### Scenario: Close during export

- **WHEN** the user closes the window while an export is encoding a clip
- **THEN** the window stays open with a message, the export stops after the current clip, the manifest is saved once, and the window closes

#### Scenario: Stage does not stop in time

- **WHEN** a project is closed and its stage does not stop within `gui.close_wait_ms`
- **THEN** closing reports failure, nothing is saved, and the project stays open

### Requirement: Worker lifetime

A worker thread SHALL be released once its stage has ended.

#### Scenario: Several stages

- **WHEN** the user runs three stages one after another
- **THEN** no finished worker thread remains alive

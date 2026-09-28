## ADDED Requirements

### Requirement: Export summary measured off the UI thread

The size of the selects folder shown in the export summary SHALL be measured by the export worker, not on the UI thread.

#### Scenario: Large selects folder

- **WHEN** an export finishes into a folder with many clips
- **THEN** the summary shows the folder size and the window did not walk the folder on the UI thread

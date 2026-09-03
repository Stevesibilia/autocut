## Purpose

Source classification assigns each file a class (`drone`, `actioncam`, `phone`, `reflex`, `generic`) that drives per-class thresholds, trims and export rules, derived from observed signals and overridable by the user.

## ADDED Requirements

### Requirement: Classification from observed signals

The system SHALL derive the class from, in decreasing weight: telemetry kind, make and model tags, frame rate, display aspect ratio and rotation, and filename pattern. A file with drone telemetry MUST be `drone`. A file with a make or model tag naming a known action camera family (`OsmoAction`, `GoPro`, `Insta360`) MUST be `actioncam`. A file with an Android or Apple manufacturer tag MUST be `phone`. A file with a make tag naming a camera manufacturer (`FUJIFILM`, `SONY`, `Canon`, `NIKON`, `Panasonic`) MUST be `reflex`. Files matching none of these MUST be `generic`.

#### Scenario: DJI Mini 2

- **WHEN** a file has telemetry kind `dji_embedded_srt` and no make tag
- **THEN** the class is `drone`

#### Scenario: Osmo Action 4

- **WHEN** a file has encoder or model tag containing `OsmoAction`
- **THEN** the class is `actioncam`

#### Scenario: Xiaomi phone

- **WHEN** a file has tag `com.android.manufacturer` set to `Xiaomi`
- **THEN** the class is `phone`

#### Scenario: Unknown camera

- **WHEN** a file has no telemetry, no make or model tags and an ordinary frame rate
- **THEN** the class is `generic`

### Requirement: Filename pattern as weak hint only

The system SHALL use filename patterns (`DJI_`, `GX`, `IMG_`, `VID_`, `DSC_`) only when no stronger signal decides the class, and MUST record in the manifest which signal decided.

#### Scenario: Pattern overruled by tag

- **WHEN** a file named `VID_0001.mp4` carries a make tag `FUJIFILM`
- **THEN** the class is `reflex` and the deciding signal is `make_tag`

### Requirement: User overrides

The system SHALL apply class overrides from configuration, each a glob matched against the file path relative to its source folder, in order, with the last match winning. An override MUST set `class_overridden` to true on the manifest entry.

#### Scenario: Folder override

- **WHEN** configuration has an override with glob `GoPro/**` and class `actioncam`, and a file lives at `GoPro/GX010001.MP4`
- **THEN** the file is classified `actioncam` with `class_overridden` true regardless of its tags

### Requirement: Class visible in output

The class and the deciding signal SHALL be present in the manifest for every file so that the review report can show them and the user can correct misclassification.

#### Scenario: Manifest fields

- **WHEN** ingest completes
- **THEN** every file entry has `source_class`, `class_signal` and `class_overridden`

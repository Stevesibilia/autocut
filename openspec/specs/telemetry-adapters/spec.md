# telemetry-adapters Specification

## Purpose

Telemetry adapters detect and parse per-file sensor data (height, speed, GPS, exposure) into one common time series so that rejection rules and reports can use it regardless of camera brand.

## Requirements

### Requirement: Adapter detection by capability

The system SHALL select a telemetry adapter for a file by probing for the data the adapter understands, not by brand or filename. The first adapter whose detection succeeds is used. When no adapter matches, the file's telemetry kind MUST be `none` and processing MUST continue with image metrics only.

#### Scenario: DJI embedded subtitle

- **WHEN** a file has a subtitle stream whose first cue matches the DJI telemetry pattern (fields such as `ISO`, `GPS (`, `H `)
- **THEN** the telemetry kind is `dji_embedded_srt`

#### Scenario: Sidecar SRT

- **WHEN** a file has no telemetry subtitle stream but a file with the same stem and extension `.srt` exists containing DJI telemetry cues
- **THEN** the telemetry kind is `dji_sidecar_srt`

#### Scenario: No telemetry

- **WHEN** a phone file has neither telemetry stream nor sidecar
- **THEN** the telemetry kind is `none` and no error is raised

### Requirement: Common telemetry time series

Each adapter SHALL return samples with a time offset in seconds from file start and optional fields: relative height in meters, horizontal speed in meters per second, vertical speed in meters per second, latitude, longitude, GPS altitude, ISO, shutter speed, exposure value. Missing fields MUST be null, never zero.

#### Scenario: DJI cue parsed

- **WHEN** a cue reads `F/2.8, SS 50.00, ISO 200, EV +1.0, DZOOM 1.000, GPS (9.6850, 39.9664, 18), D 1.76m, H 22.70m, H.S 0.00m/s, V.S -0.00m/s`
- **THEN** the sample has height 22.70, horizontal speed 0.0, vertical speed 0.0, longitude 9.6850, latitude 39.9664, GPS altitude 18, ISO 200, shutter 50.0, exposure value 1.0

#### Scenario: Malformed cue

- **WHEN** a cue cannot be parsed
- **THEN** the cue is skipped, a warning is recorded on the file, and parsing continues

### Requirement: Telemetry summary on the manifest

The system SHALL store on each manifest file entry a summary of its telemetry: minimum and maximum height, mean horizontal speed, first GPS position, and number of samples. Full samples are stored in the analysis cache, not in the manifest.

#### Scenario: Drone file summary

- **WHEN** a drone file with 20 telemetry samples is ingested
- **THEN** the manifest entry has sample count 20 and min and max height computed over the samples

### Requirement: Subtitle stream extraction through ffmpeg

The embedded subtitle adapter SHALL extract the telemetry track through the ffmpeg binary to SRT text without decoding video, and MUST complete in under two seconds for a 30 second 4K file on the development machine.

#### Scenario: Extraction cost

- **WHEN** telemetry is extracted from a 36 second 4K H.264 file
- **THEN** no video frames are decoded and the extraction finishes in under two seconds

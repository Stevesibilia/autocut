# footage-ingest Specification

## Purpose

Footage ingest turns one or more source folders into a manifest of probed, ordered video files with their proxies and cache keys, ready for analysis.

## Requirements

### Requirement: Recursive scan of accepted video files

The system SHALL scan every given source folder recursively and collect files whose extension, compared case-insensitively, is one of `.mp4`, `.mov`, `.mkv`, `.avi`, `.m4v`, `.insv`. Files with extension `.lrv` or `.lrf` MUST NOT be collected as sources. Hidden files and folders (name starting with `.`) MUST be skipped. Partial downloads (extension `.part`) MUST be skipped.

#### Scenario: Mixed folder

- **WHEN** a folder contains `DJI_0744.MP4`, `DJI_0001_D.MP4`, `DJI_0001_D.LRF`, `notes.txt` and `DJI_0757.MP4.part`
- **THEN** the scan yields exactly `DJI_0744.MP4` and `DJI_0001_D.MP4`

#### Scenario: Multiple source folders

- **WHEN** two folders are given and both contain accepted files
- **THEN** the manifest contains the files from both folders, each with its absolute source path

### Requirement: Probe every file with ffprobe

The system SHALL probe each collected file and record duration in seconds, width, height, rotation from side data, average frame rate, video codec name, pixel format, bit depth, color transfer, creation time, GPS location from format tags when present, make and model tags when present, and the list of subtitle and data streams with their handler names. A file that ffprobe cannot read MUST be recorded in the manifest with an error reason and MUST NOT abort the run.

#### Scenario: Vertical phone clip

- **WHEN** a file has raw dimensions 1920x1080 and a rotation side data entry of -90
- **THEN** the manifest records width 1920, height 1080 and rotation -90, and reports the display orientation as vertical

#### Scenario: 10-bit HEVC

- **WHEN** a file has pixel format `yuv420p10le`
- **THEN** the manifest records bit depth 10

#### Scenario: Corrupt file

- **WHEN** ffprobe exits with a non-zero status for a file
- **THEN** the file appears in the manifest with `error` set to the ffprobe message and the run continues with the next file

### Requirement: Proxy discovery

The system SHALL attach to each source file the proxy file that has the same stem in the same folder and extension `.lrv` or `.lrf`, compared case-insensitively. The proxy path MUST be recorded on the source file. When configuration disables proxies, no proxy MUST be attached.

#### Scenario: Action cam with LRF

- **WHEN** `DJI_20250713122959_0194_D.MP4` and `DJI_20250713122959_0194_D.LRF` are in the same folder
- **THEN** the manifest entry for the MP4 has `proxy_path` pointing to the LRF

#### Scenario: Proxies disabled

- **WHEN** `analysis.use_proxies` is false
- **THEN** no manifest entry has a proxy path even when LRF files exist

### Requirement: Cache key per file

The system SHALL compute for each file a cache key derived from file size, modification time, and a hash of the first and last megabyte of content. The key MUST be identical for two byte-identical copies of a file with the same size and mtime at different paths, and MUST differ when the content of the first or last megabyte differs.

#### Scenario: Copied file

- **WHEN** a file is copied with size and mtime preserved to another folder
- **THEN** both copies receive the same cache key

#### Scenario: Different content

- **WHEN** two files have equal size and mtime but different first megabyte
- **THEN** their cache keys differ

### Requirement: Chronological order

The system SHALL order files by creation time, falling back to file modification time when creation time is absent, and SHALL assign the order across all source folders and source classes together. Ties MUST be broken by path.

#### Scenario: Mixed devices

- **WHEN** a drone file has creation time 13:37, a phone file 13:39 and an action cam file 13:38 on the same day
- **THEN** the manifest order is drone, action cam, phone

### Requirement: Progress reporting

The system SHALL emit a progress event for each file probed, carrying the stage, current index, total count and file path, through the core callback and MUST NOT print to standard output from the core library.

#### Scenario: CLI progress

- **WHEN** `autocut analyze` runs on ten files
- **THEN** ten probe progress events are emitted and the CLI renders a progress bar from them

### Requirement: Manifest written by analyze

The `autocut analyze` command SHALL write `manifest.json` in the output folder with every scanned file, its probe results, proxy, telemetry kind, class and cache key, and SHALL then run segmentation, analysis and rejection rules for every successfully probed file, writing the resulting segments with metrics, scores, outcomes and thumbnails into the same manifest. The command SHALL exit with status 0 when at least one file was probed successfully. When no accepted files are found the command SHALL exit with a non-zero status and a clear message. The manifest MUST be written after ingest and again after analysis so an interrupted run leaves a usable file list.

#### Scenario: Successful ingest

- **WHEN** `autocut analyze ./footage --out ./edit` runs on a folder with accepted files
- **THEN** `./edit/manifest.json` exists, validates against the manifest schema, lists every file and contains at least one segment with a score for every file that was probed successfully

#### Scenario: Empty folder

- **WHEN** the source folder has no accepted files
- **THEN** the command exits non-zero and prints that no video files were found

#### Scenario: Interrupted analysis

- **WHEN** analysis is interrupted after ingest completed
- **THEN** `manifest.json` exists with every file and the segments completed so far

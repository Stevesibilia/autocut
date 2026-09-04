## Purpose

The montage preview plays the selected edit as one continuous low resolution file, with the track when there is one, so the user judges the sequence and the cuts before exporting.

## ADDED Requirements

### Requirement: Render from the effective windows

The system SHALL render `preview/montage.mp4` under the output folder from the selected segments in edit order, each cut to its effective window (user bounds, then beat bounds, then the target duration around the best center, the same precedence export uses), scaled to `gui.montage_height` (default 360) with an even width, at the export target frame rate, encoded with a fast preset, reading proxies when present. Clip audio SHALL be dropped; when a track is loaded on the project it SHALL be muxed in, trimmed to the montage length.

#### Scenario: Twenty-nine clips

- **WHEN** 29 clips totalling 76.0 s are selected and a track is loaded
- **THEN** the montage lasts 76.0 s within one frame, has one video stream at 360 px and the track as its audio

#### Scenario: No track

- **WHEN** no track is loaded
- **THEN** the montage has a video stream and no audio stream

### Requirement: Fingerprint and cache

The render SHALL be keyed by a fingerprint of the selected segment ids, their effective windows, the frame rate, the height and the track file identity, stored in the manifest `preview` block. A second request with the same fingerprint MUST NOT render again. A changed selection or bound MUST invalidate it.

#### Scenario: Reject one clip

- **WHEN** the user rejects a clip after a montage was built
- **THEN** the next Play all renders a new montage and the old file is removed

### Requirement: Clip index

The system SHALL write `preview/montage.json` listing each clip's order, segment id and cumulative start and end in the montage, so a player can map a time to a clip.

#### Scenario: Map time to clip

- **WHEN** playback is at 12.4 s and the index says clip 5 spans 10.0 to 14.0
- **THEN** the current clip is 5

### Requirement: Progress and worker

Rendering SHALL run through the worker with one progress event per clip and honor cancel between clips. On the Sardinia project the render SHALL finish in under 30 s on the development host.

#### Scenario: Cancel

- **WHEN** the user cancels during the render
- **THEN** no partial montage is recorded and the previous one, if any, stays valid

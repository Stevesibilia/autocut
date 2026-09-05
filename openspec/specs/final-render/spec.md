# final-render Specification

## Purpose

The final render turns the exported clips and the synced track into one finished file, for edits that need no further work in an editor.

## Requirements

### Requirement: Render from the exported clips

`autocut render <project>` SHALL concatenate the exported clips in `_selects/` in selection order by stream copy, without re-encoding video, and write `render.filename` (default `montage.mp4`) in the output folder. When the export is missing or its fingerprint does not match the current selection, the render SHALL run export first.

#### Scenario: Twenty-nine clips

- **WHEN** 29 clips totalling 73.6 s are exported and render runs
- **THEN** `montage.mp4` lasts 73.6 s within one frame, at the export resolution and frame rate, with one video stream

#### Scenario: Export stale

- **WHEN** a clip was rejected since the last export
- **THEN** render re-exports before concatenating

### Requirement: Soundtrack muxed

When a synced track exists, or `--track` names one, the render SHALL mux it as the audio stream, trimmed to the edit length with a fade out of `render.fade_out_seconds` (default 1.5) when the track is longer, and padded with silence when shorter. Without a track the render SHALL have no audio stream unless clips kept their own audio, in which case clip audio SHALL be concatenated.

#### Scenario: Longer track

- **WHEN** the track is 79.6 s and the edit 73.6 s
- **THEN** the audio ends at 73.6 s with a 1.5 s fade out

#### Scenario: No track, silent clips

- **WHEN** no track exists and every clip is silent
- **THEN** the render has no audio stream

### Requirement: Fingerprint

The render SHALL be keyed by the export fingerprint, the track identity and the fade length, recorded in the manifest, and MUST NOT rerun when unchanged.

#### Scenario: Second render

- **WHEN** render runs twice without changes
- **THEN** the second run writes nothing and reports the existing file

### Requirement: Report and summary

The report header and the Export screen summary SHALL show the render file, its duration and size when present.

#### Scenario: Summary

- **WHEN** a render exists
- **THEN** the Export summary names the file with duration and size and offers to open it

# clip-export Specification

## Purpose

Clip export cuts each selected segment out of its source file and normalizes it so every output plays identically in CapCut without on-the-fly conversion.
## Requirements
### Requirement: Precise and fast cut modes

In `precise` mode the system SHALL re-encode the clip with the configured codec and CRF so that in and out points are frame exact. In `fast` mode it SHALL stream copy aligned to keyframes and MUST record on the segment that durations are approximate. Precise is the default. The cut window SHALL be the segment's final bounds when beat sync has set them, otherwise the target duration centered on the best window center.

#### Scenario: Exact duration

- **WHEN** a 3.0 second window is exported in precise mode at 25 fps
- **THEN** the output duration is 3.0 seconds within one frame (0.04 s)

#### Scenario: Fast mode flagged

- **WHEN** a clip is exported in fast mode
- **THEN** the manifest segment records `export_mode: fast` and the report shows the approximate duration marker

#### Scenario: Beat bounds win

- **WHEN** a clip has target 2.2 s and final bounds of 2.0 s from beat sync
- **THEN** the exported clip lasts 2.0 s within one frame

### Requirement: Frame rate normalization

The target frame rate SHALL be `export.fps` when numeric. Otherwise it SHALL be chosen from the frame rates present among the selected clips, taking the one that the most selected clips reach by whole-number division, where a clip reaches a target when its frame rate divided by the target is a whole number including 1. On a tie the lowest rate SHALL win. Every output SHALL have the target frame rate. A clip converted from a frame rate that is not the target or a whole multiple of it SHALL be flagged `fps_converted` on the segment.

#### Scenario: Auto picks the rate most clips divide into

- **WHEN** selected clips are 24 at 50 fps, 14 at 25 fps and 2 at 30 fps
- **THEN** the target is 25, because 38 clips reach it against 24 that reach 50, and only the 30 fps clips are flagged

#### Scenario: One frame rate everywhere

- **WHEN** every selected clip is 30 fps
- **THEN** the target is 30 and nothing is flagged

#### Scenario: Two rates that do not divide into each other

- **WHEN** selected clips are 12 at 24 fps and 8 at 30 fps
- **THEN** the target is 24, the rate the larger group reaches, and the 30 fps clips are flagged

#### Scenario: Tie

- **WHEN** selected clips are 10 at 24 fps and 10 at 30 fps
- **THEN** the target is 24, because a tie goes to the lower rate

### Requirement: Resolution and pixel format

Outputs SHALL be scaled down to fit `export.max_width` by `export.max_height` preserving aspect ratio, MUST NOT be upscaled, and SHALL be `yuv420p` unless `export.pix_fmt` is `passthrough`. Rotation side data SHALL be applied so the output has no rotation metadata.

When `export.uniform_frame` is true, or the export runs for a render, every selected clip SHALL instead be scaled to fit one common frame and padded to it centred, where the common frame's height is the smallest of the selected clips' fitted heights and its width is that of the widest clip scaled to that height, capped at `export.max_width`, so that no clip is upscaled and a single narrower clip is padded rather than narrowing the frame. The frame SHALL be recorded on the manifest and, on a later export of the same project, SHALL be the smaller of the recorded frame and the current smallest fitted size, so a frame never grows. Vertical strategies SHALL take the common frame as their canvas when it is on, so `blur_pad` and `center_crop` outputs equal the frame exactly. The report and the Export summary SHALL name the frame.

#### Scenario: Phone clip not upscaled

- **WHEN** a 1920x1080 source is exported with a 3840x2160 maximum
- **THEN** the output is 1920x1080

#### Scenario: 10-bit source

- **WHEN** a `yuv420p10le` source is exported with default pixel format
- **THEN** the output is `yuv420p`

#### Scenario: Mixed sizes under a render

- **WHEN** 9 clips at 3840x2160 and 20 at 1920x1080 are exported for a render with the default maximum
- **THEN** every output is 1920x1080, the 4K clips are scaled and the 1080 clips get no scale filter, and the manifest records a 1920x1080 frame

#### Scenario: Different aspect inside the frame

- **WHEN** a 1440x1080 clip is exported into a 1920x1080 frame
- **THEN** it is kept at 1440x1080 and padded to 1920x1080 with the picture centred

#### Scenario: Frame never grows

- **WHEN** the only 1920x1080 clip of an edit recorded at that frame is rejected and the export runs again
- **THEN** the frame stays 1920x1080 and no 4K clip is re-encoded larger

#### Scenario: Vertical clip on the frame

- **WHEN** a 1080x1920 vertical clip is exported with `blur_pad` into a 1920x1080 frame
- **THEN** the output is exactly 1920x1080

#### Scenario: Fast mode cannot render

- **WHEN** `autocut render` runs on a project with `export.mode = "fast"`
- **THEN** it exports nothing and says that a render needs precise mode

### Requirement: Audio per class

Audio SHALL be removed when `export.remove_audio` is true for the segment's class and kept otherwise. The default is true for every class, so a default export is silent and the soundtrack carries the sound; a user who wants ambience sets the class to false in `autocut.toml`. `--no-audio` removes it for every clip regardless of configuration.

#### Scenario: Silent by default

- **WHEN** a drone clip and a phone clip are exported with defaults
- **THEN** neither output has an audio stream

#### Scenario: Drone silent, phone keeps ambience

- **WHEN** `export.remove_audio.phone` is false
- **THEN** the phone output keeps its audio and the drone output has none

### Requirement: Slow motion

When `export.slow_motion_auto` is true for the class and the source fps is at least twice the target fps, the clip SHALL be exported at real-frame slow motion by the integer ratio, and the window duration in source time SHALL be divided by the ratio so the output still lasts the target duration.

#### Scenario: Action cam at 50 fps

- **WHEN** a 50 fps action cam window of 3 seconds output is exported to 25 fps with slow motion on
- **THEN** 1.5 seconds of source around the best center become 3.0 seconds of output at half speed

### Requirement: Vertical strategies

With strategy `blur_pad` a vertical clip SHALL be placed on a blurred, scaled copy of itself filling the target aspect. With `center_crop` it SHALL be cropped to the target aspect around the center. With `exclude` no vertical clip reaches export.

#### Scenario: Blur pad

- **WHEN** a 1080x1920 display-vertical clip is exported with `blur_pad` and a 16:9 target
- **THEN** the output is 16:9 with the clip centered and blurred sides

### Requirement: LUT and lens hooks

When `export.lut` names a `.cube` file for the class it SHALL be applied with `lut3d`; when `export.lens_correction` is true for the class a `lenscorrection` filter with configured coefficients SHALL be applied. Neither is on by default.

#### Scenario: Drone LUT

- **WHEN** `export.lut.drone` points to a file
- **THEN** the drone clip's filter chain contains `lut3d` with that path and other classes' chains do not

### Requirement: Command construction is testable

The ffmpeg argument list for a clip SHALL be built by a pure function from the segment, file and configuration and MUST be unit testable without running ffmpeg.

#### Scenario: Argument list

- **WHEN** the command for a precise drone clip is built
- **THEN** it contains `-ss`, `-t`, `-an`, the `fps` and `scale` filters, `-c:v libx264 -crf 18 -pix_fmt yuv420p` and the output path

### Requirement: Resumable parallel export

Export SHALL run clips in parallel, skip a clip whose output exists and whose manifest entry matches the current window and settings, emit an `export` progress event per clip, and write `exported_path` on each segment. A failing clip MUST be recorded with its ffmpeg error and MUST NOT stop the others.

#### Scenario: Second run

- **WHEN** export runs twice without changes
- **THEN** the second run encodes nothing and reports every clip skipped

#### Scenario: One bad file

- **WHEN** one source file is unreadable at export time
- **THEN** the other clips are exported and the failed segment records the error

### Requirement: No partial clip after a failure

A clip whose encode fails for any reason, including a timeout, SHALL leave no file at its output path, so that a later run cannot mistake it for a finished clip. An exception raised while exporting one clip SHALL be recorded as that clip's failure and SHALL NOT stop the other clips.

#### Scenario: Encode times out

- **WHEN** ffmpeg times out after writing part of a clip
- **THEN** the clip's output file does not exist and the clip is recorded as failed

#### Scenario: One worker raises

- **WHEN** the worker for one clip raises an unexpected exception
- **THEN** that clip is recorded as failed and the other clips are exported


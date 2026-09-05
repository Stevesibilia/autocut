## MODIFIED Requirements

### Requirement: Resolution and pixel format

Outputs SHALL be scaled down to fit `export.max_width` by `export.max_height` preserving aspect ratio, MUST NOT be upscaled, and SHALL be `yuv420p` unless `export.pix_fmt` is `passthrough`. Rotation side data SHALL be applied so the output has no rotation metadata.

When `export.uniform_frame` is true, or the export runs for a render, every selected clip SHALL instead be scaled to fit one common frame and padded to it centred, where the common frame is the smallest of the selected clips' fitted sizes (by height, then width), so that no clip is upscaled. The frame SHALL be recorded on the manifest and, on a later export of the same project, SHALL be the smaller of the recorded frame and the current smallest fitted size, so a frame never grows. Vertical strategies SHALL take the common frame as their canvas when it is on, so `blur_pad` and `center_crop` outputs equal the frame exactly. The report and the Export summary SHALL name the frame.

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

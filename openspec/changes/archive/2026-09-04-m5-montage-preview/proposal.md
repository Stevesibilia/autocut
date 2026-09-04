## Why

The Review screen previews one clip at a time. Judging an edit means watching the clips in sequence, the way CapCut plays them after import, and hearing whether the cuts land on the music. The user asked for exactly this after the first hands-on test. A low resolution montage rendered from the proxies gives seamless playback and shows the beat sync for real, before anything is exported.

## What Changes

- Core: `montage.py` renders `preview/montage.mp4` from the selected clips in edit order using each clip's effective window (user bounds, beat bounds or the best window), at `gui.montage_height` (default 360 px) with a fast preset, from proxies when present, muxing the loaded track when one exists, and writes a `preview/montage.json` index of cumulative clip starts. Output keyed by a fingerprint of the selection, bounds and track so it rebuilds only when the edit changes.
- Review screen: a Play all button and a montage player with a timeline showing clip boundaries; clicking a boundary jumps there and selects that card in the grid; the current clip is highlighted while playing; keyboard shortcuts keep working during playback so a clip can be rejected as it plays.
- Soundtrack screen: after Apply sync, Play with track renders the montage with the audio muxed and plays it, so drift is heard rather than inferred.
- Build runs through the worker with progress; stale previews are removed with the project's stale outputs.

## Capabilities

### New Capabilities

- `montage-preview`: rendering and playing the selected edit as one low resolution file.

### Modified Capabilities

- `gui-review`: Play all and the montage timeline join the preview requirement.
- `gui-soundtrack`: Play with track after sync.

## Impact

- New module `autocut/core/montage.py` reusing `plan_export` for windows and `ffmpeg_cmd` conventions; `autocut/gui/widgets/montage.py`.
- Manifest gains `preview` block with fingerprint and path; `gui.montage_height`, `gui.montage_preset` in config.
- Depends on the fix for issue #38 (video output in the preview widget).

## Why

Selected clips exist only as numbers in the manifest until they are cut. This change writes the `_selects/` folder that the whole project exists to produce: numbered, normalized clips that drop into CapCut in one go. It completes milestone M2 (SPEC.md section 7.7 and 7.8).

## What Changes

- ffmpeg command builder for one clip: precise re-encode (default) or fast stream copy, as an argument list testable without running ffmpeg.
- Normalization: frame rate (`auto` picks the dominant fps among selected clips), downscale only to the configured maximum, 8-bit `yuv420p` by default, audio removal per class.
- Automatic slow motion for classes configured for it when the source fps is at least twice the target.
- Vertical clip strategies: exclude (default, applied at select time), blur padded sides, center crop.
- LUT per class through `lut3d` and optional lens correction for action cams, as hooks driven by configuration.
- Output naming `{index:03d}_{date}_{class}_{tag}_{duration}s.mp4` with tag `clip` until semantic tags exist, into `_selects/`, plus optional `_rejects/`.
- `autocut export` command with `--no-audio`, `--fps`, `--fast`, `--rejects` overrides, parallel over clips, resumable: existing outputs with matching manifest entries are skipped.
- Report links each selected card to its exported file.

## Capabilities

### New Capabilities

- `clip-export`: cutting and normalizing one selected segment into an output file.
- `output-naming`: deterministic file names and folder layout that carry order into CapCut.

### Modified Capabilities

- `clip-selection`: vertical clips are excluded from eligibility when the vertical strategy is `exclude`.

## Impact

- New modules under `autocut/core/`: `ffmpeg_cmd.py`, `export.py`, `naming.py`.
- `autocut/core/manifest.py`: `Segment.exported_path` is filled; `Manifest` gains an `export` block with the target fps, resolution and mode used.
- Depends on `m2-select`.

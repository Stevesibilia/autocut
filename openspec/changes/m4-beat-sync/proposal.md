## Why

Once the user brings back the Suno track, clips should already sit on its beats, so CapCut's beat sync has nothing to fix. SPEC.md section 7.6 specifies it and `m3-durations` fixed the contract: beat sync quantizes the assigned durations to beat multiples rather than deriving them from score. This change closes the two-pass loop.

## What Changes

- Beat tracking on the provided audio with librosa: BPM and beat positions, with `--bpm` override and a warning when the measured BPM differs from the proposed one beyond `soundtrack.bpm_tolerance`, including the half and double tempo cases.
- Quantization of every selected clip's assigned duration to the nearest allowed beat multiple, hero clips rounding up on ties, clamped to the segment span, with the alternation pattern preserved where the segments allow.
- Final bounds `final_start_s` and `final_end_s` stored on each segment, centered on the best window center, snapped to the sampling grid, inside the trimmed span.
- `beatmap.txt` with beat times and the cumulative clip boundaries, for reference in CapCut.
- `autocut sync <project> --audio <file> [--bpm N]`; export uses final bounds when present; report shows quantized durations and the BPM comparison.

## Capabilities

### New Capabilities

- `beat-sync`: measuring the track, quantizing durations to beats and writing the beat map.

### Modified Capabilities

- `clip-durations`: a quantization stage after assignment when a track exists.
- `clip-export`: cuts use the final bounds when beat sync has run.

## Impact

- New module `autocut/core/beatsync.py`; `export.py` reads final bounds; `report.py` shows them.
- `autocut/core/manifest.py`: `Soundtrack.measured_bpm`, `bpm_override`, `beats_s`, `audio_path` filled; `Segment.final_start_s`, `final_end_s`, `beats` filled.
- Dependency `librosa` already declared; audio decoding goes through ffmpeg to WAV first so librosa never touches container formats.
- Depends on `m4-soundtrack-prompt` only for the proposed BPM comparison; runs without it.

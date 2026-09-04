## Why

With the review done, the user needs the two remaining screens of SPEC.md section 11: the soundtrack screen that carries the two-pass music loop (prompt out, track in), and the export screen that writes the folder for CapCut. Both are thin over existing core commands; the value is in showing the prompt with copy buttons, the waveform with beats, and the export options in one place.

## What Changes

- Soundtrack screen, first half: the three prompt blocks with copy buttons, variant switcher, editable BPM that regenerates, mood controls (calmer or more energetic, cinematic or intimate) that pick alternates within the matched row, genre row override, hand editing with live validation marking each violated rule inline, refinement toggle with cost shown when cloud is on.
- Soundtrack screen, second half: load a track, waveform with detected beats, measured versus proposed BPM with the drift warning and half or double tempo suggestion, BPM override, beat multiple distribution preview before applying sync.
- Export screen: target fps and resolution, mode, codec, audio per class, vertical strategy, slow motion, LUT per class, rejects folder; progress per clip through the worker; open the output folder on completion; summary of durations and size.
- Waveform rendering from the decoded audio as a downsampled envelope, cached next to the manifest.

## Capabilities

### New Capabilities

- `gui-soundtrack`: prompt editing and track syncing in the GUI.
- `gui-export`: export configuration and execution in the GUI.

### Modified Capabilities

- `soundtrack-prompt`: mood controls select alternates within the matched row; the prompt MAY be edited by hand and stored as the chosen variant when valid.

## Impact

- GUI: `screens/soundtrack.py`, `screens/export.py`, `widgets/prompt_editor.py`, `widgets/waveform.py`.
- Core: `soundtrack/prompt.py` gains `apply_mood(prompt, row, calm_energetic, cinematic_intimate)`; `beatsync.py` gains `envelope(samples, sr, points)` for the waveform; manifest `Soundtrack.chosen_variant` may hold a hand-edited prompt with `source: user`.
- Depends on `m5-gui-review`.

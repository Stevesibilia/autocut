## Context

The shell and review screens exist (ADR 9). `autocut soundtrack`, `autocut sync` and `autocut export` are complete core stages with progress events. The validator returns every violation with a line number, which is what inline marking needs. Beat sync decodes audio through ffmpeg into NumPy; a waveform envelope is a reduction of the same samples.

## Goals / Non-Goals

**Goals:**

- The music loop without leaving the app: copy, generate elsewhere, load, sync.
- Export options that a non-CLI user can understand, written to the same `autocut.toml` the CLI reads.

**Non-Goals:**

- Audio playback synced with clips (a montage preview is M5+ if ever).
- Calling a music API.

## Decisions

**Prompt editor.** `QPlainTextEdit` per block with a validator pass on a 150 ms debounce; violations become `QTextEdit.ExtraSelection` underlines with the rule in a tooltip and a list below. Copy uses `QClipboard`; an invalid block copies only after a confirmation.

**Mood controls.** Two `QSlider` with three positions each. `apply_mood` in the core maps positions to alternate picks in the matched row (calmer picks the softer instrument adjectives and moods, cinematic picks wider ones), then regenerates variants. Kept in the core so the CLI can expose `--mood` later.

**Waveform.** `beatsync.envelope` downsamples the mono signal to about 2000 min and max pairs, cached as `.npy` next to the manifest keyed by the audio file's size and mtime. Painted in a custom `QWidget` with beat ticks from `beats_s`.

**Sync preview.** Runs `quantize_durations` in dry mode against the chosen BPM to show the multiple distribution and total before Apply; Apply runs the real stage through the worker.

**Export screen.** A form generated from the `ExportConfig` fields with per-class rows for the `PerClass` values; `plan_export` dry run shows the target fps and converted count before running. Progress from the existing `export` events; open folder via `QDesktopServices.openUrl`.

**Stale deletion.** Offered, never automatic; deletes only files under `_selects/_stale/`.

## Risks / Trade-offs

- [Clipboard in offscreen tests] → `qtbot` with the offscreen platform supports `QClipboard`; verified in CI.
- [Large audio files for the envelope] → downsampled once and cached; decode reuses the beat sync path.
- [Users edit the prompt into something valid but musically odd] → the validator guards format only; the mood controls are the guided path.

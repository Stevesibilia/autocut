## 1. Core additions

- [ ] 1.1 Add `apply_mood` to `autocut/core/soundtrack/prompt.py` and the user variant handling in `build.py` (store, validate, write first in `suno-prompt.md`). Verify with unit tests for the calmer and user-variant-first scenarios.
- [ ] 1.2 Add `beatsync.envelope(samples, sr, points)` and a dry mode for `quantize_durations`. Verify with unit tests on the click fixture.

## 2. Soundtrack screen

- [ ] 2.1 Add `widgets/prompt_editor.py` with the three blocks, copy buttons, inline validation marks and the violation list. Verify with `qtbot` tests for copy and the comma-in-a-tag scenario.
- [ ] 2.2 Add `screens/soundtrack.py` first half: variants, BPM field, genre row override, mood sliders, refinement toggle with cost. Verify with `qtbot` tests for BPM edit and calmer scenarios.
- [ ] 2.3 Add `widgets/waveform.py` and the second half: load track, waveform with beats, comparison messages, override, distribution preview, Apply through the worker. Verify with `qtbot` tests on the click fixture for the drifted (use `--bpm` style override) and apply scenarios.

## 3. Export screen

- [ ] 3.1 Add `screens/export.py` with the option form bound to config and written to `autocut.toml`, the dry-run summary, run with progress and cancel, completion summary, open folder, stale deletion offer. Verify with `qtbot` tests on the synthetic project for the keep-phone-audio, second-export and one-failure scenarios (monkeypatch one source unreadable).

## 4. Validation

- [ ] 4.1 Screenshot both screens in their main states on the synthetic project into `$AUTOCUT_GUI_SHOTS`. Run the full loop on the real Sardinia project on the Linux host: soundtrack, copy the prompt, load a track from `~/Documents/autocut/tracks/` if present else the click fixture, apply sync, export. Record time and any rough edge in this task.
- [ ] 4.2 Update `SPEC.md` section 11 (screens 4 and 5) and section 15 (M5 done). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-gui-soundtrack-export` following `sf-commit-convention`, open a pull request.

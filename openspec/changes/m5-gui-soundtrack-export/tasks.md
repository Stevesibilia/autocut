## 1. Core additions

- [x] 1.1 Add `apply_mood` to `autocut/core/soundtrack/prompt.py` and the user variant handling in `build.py` (store, validate, write first in `suno-prompt.md`). Verify with unit tests for the calmer and user-variant-first scenarios.

  `apply_mood` needed something the rows do not carry: an order. A row lists its mood words and says nothing about which is the calm one, so two scales were added to the configuration, `soundtrack.calm_to_energetic` and `soundtrack.intimate_to_cinematic`, ordering the words the shipped rows actually use. A word missing from a scale is neutral rather than guessed at, and a test asserts every shipped row's words appear in both, because a silently neutral word would make a control do nothing for reasons nobody could see.

  The prompt is rebuilt rather than patched: the Structure spreads the mood across its sections, so editing the Description alone would leave the two blocks disagreeing. A test walks every shipped row and both directions and validates the result, since a control that produced an invalid prompt would be worse than no control.

  `store_user_variant` validates first and stores nothing that fails, because the validator exists so that nothing unusable reaches Suno and that applies to a person's own typing too. It is stored first in the list, is the chosen variant, survives a regeneration and is labelled "yours, edited by hand" in the file. 24 tests.

- [x] 1.2 Add `beatsync.envelope(samples, sr, points)` and a dry mode for `quantize_durations`. Verify with unit tests on the click fixture.

  `envelope` takes the minimum and maximum of each slice rather than a mean, because a mean draws a straight line where the music is. The signature is `envelope(samples, points)`: the sample rate is not needed to reduce an array to pairs, and passing it would have been a parameter nobody reads. On the click fixture the 200 slices show exactly the 40 clicks, and a test records that the fixture peaks at 0.125 rather than assuming a full scale signal.

  `dry_run` runs the same arithmetic and writes nothing, and a test asserts the preview and the real run agree on every number, because a preview that disagreed with the run would be worse than no preview.

## 2. Soundtrack screen

- [x] 2.1 Add `widgets/prompt_editor.py` with the three blocks, copy buttons, inline validation marks and the violation list. Verify with `qtbot` tests for copy and the comma-in-a-tag scenario.

  Each violated rule becomes a wavy underline on its own line with the rule in a tooltip, plus a line in the list below, which is what the validator's line numbers were for. Copying an invalid block asks rather than refuses: the rules are Suno's and they change, so the user may know better than the validator. The instrument list travels with the variant rather than being parsed back out of the text, because the validator needs to know which words were meant as instruments and re-deriving that from something a person has been editing is guesswork.

- [x] 2.2 Add `screens/soundtrack.py` first half: variants, BPM field, genre row override, mood sliders, refinement toggle with cost. Verify with `qtbot` tests for BPM edit and calmer scenarios.

  Mood is two combo boxes with three positions rather than sliders: the axes have three states, and a slider that can only be in three places is a slider that lies about being continuous. **Each position is absolute.** Moves are applied to the variants as generated, kept in `_generated`, not to the last result: applied to their own output, "as matched" left whatever the previous position had chosen, which the real footage run caught. The refinement note says whether a hosted model will be called and why not when it will not.

- [x] 2.3 Add `widgets/waveform.py` and the second half: load track, waveform with beats, comparison messages, override, distribution preview, Apply through the worker. Verify with `qtbot` tests on the click fixture for the drifted (use `--bpm` style override) and apply scenarios.

  The envelope is cached beside the manifest, keyed by the audio file's size and modification time: hashing a hundred megabytes to avoid decoding it is not a saving, and a track replaced under the same name has a different mtime. The half and double cases pre-fill the override with the proposed BPM, since that is the tracker's usual mistake and the fix is one field away. The override field goes to 400 rather than the prompt field's 220, because a tracker reading double a slow track gives a number no prompt would have asked for.

## 3. Export screen

- [x] 3.1 Add `screens/export.py` with the option form bound to config and written to `autocut.toml`, the dry-run summary, run with progress and cancel, completion summary, open folder, stale deletion offer. Verify with `qtbot` tests on the synthetic project for the keep-phone-audio, second-export and one-failure scenarios (monkeypatch one source unreadable).

  26 tests, three of them running real exports of the synthetic clips. The screen asks whether to **keep** the audio where the configuration asks whether to **remove** it, because that is the question a person has.

  Writing the per class tables needed two fixes. `write_config` treated a `PerClass` model as a scalar and wrote its repr, which read back as a string and replaced the table; it now dumps the model. And every key of a per class table has to be present when it is read back, while TOML has no null, so an unset LUT is written as an empty string and `ExportConfig` reads that back as no LUT. Both are covered.

  Stale deletion removes only files directly under `_selects/_stale/`, and a test puts a file in a subfolder to prove it is left alone: this is a delete button in a folder the user chose, and the narrowest reading of what it may remove is the only safe one.

## 4. Validation

- [x] 4.1 Screenshot both screens in their main states on the synthetic project into `$AUTOCUT_GUI_SHOTS`. Run the full loop on the real Sardinia project on the Linux host: soundtrack, copy the prompt, load a track from `~/Documents/autocut/tracks/` if present else the click fixture, apply sync, export. Record time and any rough edge in this task.

  Seven new images on the synthetic project: `soundtrack-empty`, `soundtrack-prompt`, `soundtrack-invalid-edit`, `soundtrack-track`, `soundtrack-synced`, `export-options`, `export-done`, alongside the review and shell ones. Paths in the pull request body, nothing committed, synthetic fixtures only.

  **`~/Documents/autocut/tracks/` still does not exist, so the loop used the synthetic click fixture** and the run says so. Real run against `~/Documents/autocut/test sardegna`, output in `~/Documents/autocut/edit-sardegna-m5-final`.

  | Step                    | Result                                                                 |
  | ----------------------- | ---------------------------------------------------------------------- |
  | Analysis, warm cache    | 10.9 s, 77 segments, 29 clips selected                                 |
  | Soundtrack screen ready | under 1 ms                                                             |
  | Prompt generated        | 9 ms, 3 variants, valid, `surf rock` matched on the dominant beach tag |
  | Copy                    | The clipboard held exactly the Description                             |
  | Mood, calmer            | `breezy` in place of `sunny`, genre unchanged                          |
  | Mood, more energetic    | `playful`, genre unchanged                                             |
  | Mood, as matched        | back to `sunny` (after the fix below)                                  |
  | Track load and measure  | 3.3 s for the 20 s click, 38 beats drawn, comparison agreed            |
  | Sync preview            | 29 clips, 76.5 s becomes 76.0 s, 19 x 4, 4 x 6, 5 x 8, 1 x 12 beats    |
  | Apply sync              | under 1 s, 29 of 29 clips on the grid, mean move 0.21 s                |
  | Export                  | 161.2 s, 29 clips written, 0 failed, 623 MB, 19 slowed, 1 resampled    |
  | Second export           | under 1 s, 29 skipped, 0 written                                       |
  | Errors                  | None                                                                   |

  **The rough edge the run found, and the fix:** "as matched" did not go back. Each mood move was applied to the previous result, so once the words had moved there was nothing left to return to. The screen now keeps the variants as generated and applies every position to those, which also means asking for calmer twice is not calmer twice. Two tests cover it.

  Also fixed while here, from the pull request 34 review: the groups view labelled clips with the segment's content hash and now shows the file name and the time, with the id on the tooltip; and a card in the review grid now carries a coloured border and a corner badge (`IN 3`, `KEPT 5`, `OUT`) rather than only a number in a row of numbers.

- [x] 4.2 Update `SPEC.md` section 11 (screens 4 and 5) and section 15 (M5 done). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-gui-soundtrack-export` following `sf-commit-convention`, open a pull request.

  Section 11 now describes both screens and the two mood scales; section 15 marks M5 complete. **Section 11 also needed repairing:** the paragraph the previous change added between the numbered items had swallowed items 4 and 5 into itself once prettier reflowed it, so the last two screens were not list items at all.

  Gates: `make lint` clean (ruff, format, mypy strict on 69 files). `make docker-test` **1049 passed, 59 skipped**. `make docker-test-gui` **217 passed**. `make docker-test-ai` **8 passed, 11 skipped**. Both mypy passes hold: excluded on the Qt free image (46 files), full in `dev-gui` (69 files). In the venv, **1274 passed, 40 skipped**.

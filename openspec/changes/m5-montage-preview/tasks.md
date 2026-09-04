## 1. Core

- [ ] 1.1 Add `autocut/core/montage.py` with `montage_fingerprint(manifest, config, track)`, `render_parts(manifest, config, progress)` (per clip, cached by part fingerprint, from proxy when present, 360 px ultrafast, no audio), `concat_montage(parts, track, out)` and `write_index(parts, out)`; add `gui.montage_height`, `gui.montage_preset` to config and a `preview` block to the manifest. Verify with an `ffmpeg` marked test on the synthetic selection: duration equals the sum of parts within one frame, one video stream at 360 px, no audio without a track, the click track as audio with one, a second call renders nothing, rejecting one clip re-renders only the concat.
- [ ] 1.2 Add cancel between clips leaving the previous montage valid. Verify with a test cancelling after the second part.

## 2. Player widget

- [ ] 2.1 Add `autocut/gui/widgets/montage.py` with `MontagePlayer` (video widget, transport, timeline with boundaries from the index, `clip_changed` signal, `seek_to_clip`). Verify with `qtbot` tests using a `QVideoSink` frame counter on a synthetic montage: frames arrive, `clip_changed` fires at boundaries, clicking a boundary seeks.

## 3. Screens

- [ ] 3.1 Add Play all to the Review screen: render through the worker when the fingerprint changed, play, highlight the current card, select on boundary click, route K, R, space, U to the playing clip and mark the montage stale. Verify with `qtbot` tests for the Play all and reject-while-playing scenarios.
- [ ] 3.2 Add Play with track to the Soundtrack screen after Apply sync, reusing the player. Verify with a `qtbot` test that the montage is rendered with the audio stream present.
- [ ] 3.3 Include `preview/` in the export stale sweep. Verify with a unit test.

## 4. Validation

- [ ] 4.1 On the real Sardinia project on the Linux host with a display: Play all on the 29 clip selection, then Apply sync with the click track (or a real track under `~/Documents/autocut/tracks/` if present) and Play with track. Record render time, montage duration, and whether the boundaries land on beats by ear. Screenshots of the player on the synthetic project only, to `AUTOCUT_GUI_SHOTS`.
- [ ] 4.2 Update `SPEC.md` section 11 (screens 3 and 4). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-montage-preview` following `sf-commit-convention`, open a pull request.

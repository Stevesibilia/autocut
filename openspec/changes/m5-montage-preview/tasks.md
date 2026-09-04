## 1. Core

- [x] 1.1 Add `autocut/core/montage.py` with `montage_fingerprint(manifest, config, track)`, `render_parts(manifest, config, progress)` (per clip, cached by part fingerprint, from proxy when present, 360 px ultrafast, no audio), `concat_montage(parts, track, out)` and `write_index(parts, out)`; add `gui.montage_height`, `gui.montage_preset` to config and a `preview` block to the manifest. Verify with an `ffmpeg` marked test on the synthetic selection: duration equals the sum of parts within one frame, one video stream at 360 px, no audio without a track, the click track as audio with one, a second call renders nothing, rejecting one clip re-renders only the concat.

  38 tests. Windows come from `plan_export`, so the montage cuts what the export will cut; a preview that disagreed with the export would be worse than no preview. `gui.montage_crf` was added alongside the two the task names, because the preset alone does not decide the size of the file.

  **Two things the real footage corrected.**

  `-shortest` was the obvious flag for muxing the track and it is the wrong one: the 20 s click fixture cut a 77 s edit down to 20 s, which is the opposite of a preview of the edit. The audio is padded with `apad` and the output trimmed to the montage's own duration instead, so a short track leaves the rest silent and a long one is trimmed. Two tests, one of them building a 2 s track against a 15 s montage.

  The montage came out as video, audio **and an unknown data stream**, because the concat carries the parts' data streams through and the mp4 muxer then writes a timecode track of its own. `-dn -write_tmcd 0`, the same pair `build_export_command` already carries, and a test now asserts the streams are video and audio and nothing else.

  **And one bug of my own, caught by the test the task asked for.** Parts were named `<position>_<fingerprint>.mp4`, so dropping one clip renamed every part after it and re-rendered them all, which is the one thing the per part fingerprint exists to prevent. Named by fingerprint alone now; the order is the concat list's business.

- [x] 1.2 Add cancel between clips leaving the previous montage valid. Verify with a test cancelling after the second part.

  The progress callback raises `MontageCancelled`, as the analysis stage does, and nothing is recorded until the concat has succeeded: the manifest still points at the montage that finished. A test cancels after the second part and asserts the old fingerprint and file are still there.

## 2. Player widget

- [x] 2.1 Add `autocut/gui/widgets/montage.py` with `MontagePlayer` (video widget, transport, timeline with boundaries from the index, `clip_changed` signal, `seek_to_clip`). Verify with `qtbot` tests using a `QVideoSink` frame counter on a synthetic montage: frames arrive, `clip_changed` fires at boundaries, clicking a boundary seeks.

  18 tests. The frame counter is the lesson of issue 38 applied to the second player in the application: outputs attached before any source is set, and a test that counts frames rather than trusting the widget.

  **`seek_to_clip` plays from the clip rather than showing a still.** A paused player cannot be seeked to a frame it has not decoded, so the alternative to playing is a blank rectangle; whoever wanted a still can press Pause. The timeline's own label was dropped after the first screenshot: the transport row already names the clip, and a centred string collided with the boundary boxes.

## 3. Screens

- [x] 3.1 Add Play all to the Review screen: render through the worker when the fingerprint changed, play, highlight the current card, select on boundary click, route K, R, space, U to the playing clip and mark the montage stale. Verify with `qtbot` tests for the Play all and reject-while-playing scenarios.

  Seven tests, five of them rendering real montages. `_current()` prefers the clip on screen while the montage is showing, which is what makes rejecting during playback mean what it says: pressing R is a judgement about what is being watched, not about wherever the grid cursor was left. A decision marks the montage stale and says so, and does not interrupt playback, because interrupting it would make reviewing while watching pointless.

- [x] 3.2 Add Play with track to the Soundtrack screen after Apply sync, reusing the player. Verify with a `qtbot` test that the montage is rendered with the audio stream present.

  The button is disabled until a track is loaded and a sync has run: hearing the cuts against the music is the point, and before the sync the clips are not on the grid. Three tests, one asserting the audio stream in the rendered file and one that a second press renders nothing.

- [x] 3.3 Include `preview/` in the export stale sweep. Verify with a unit test.

  The Export screen's stale button now also offers the montage when its fingerprint no longer matches the project, since a montage from an edit three decisions ago is bigger than every stale clip put together. Two tests: a stale preview is offered and removed, a current one is left alone.

## 4. Validation

- [x] 4.1 On the real Sardinia project on the Linux host with a display: Play all on the 29 clip selection, then Apply sync with the click track (or a real track under `~/Documents/autocut/tracks/` if present) and Play with track. Record render time, montage duration, and whether the boundaries land on beats by ear. Screenshots of the player on the synthetic project only, to `AUTOCUT_GUI_SHOTS`.

  Three new screenshots on the synthetic project: `montage-before`, `montage-playing`, `montage-with-track`. **The video area is empty in them, and that is the offscreen platform rather than a bug**: a `QVideoWidget` is composited by the platform and a `grab()` of it offscreen returns the widget without the video. The frame counting tests are what prove frames arrive; the screenshots show the timeline, the transport and the layout.

  Real run against `~/Documents/autocut/test sardegna`, output in `~/Documents/autocut/edit-sardegna-montage`, on Wayland with a display.

  | Measurement                  | Result                                                                                            |
  | ---------------------------- | ------------------------------------------------------------------------------------------------- |
  | Play all, 29 clips, cold     | **17.7 s**, 29 parts rendered, worst UI gap 100 ms                                                |
  | Spec's budget                | under 30 s: met                                                                                   |
  | Montage duration             | 77.24 s against 76.46 s of assigned durations                                                     |
  | Preview folder               | 51.2 MB                                                                                           |
  | Playback                     | 97 frames counted in a sink, three clip changes announced                                         |
  | Second Play all, untouched   | renders nothing, same file                                                                        |
  | After one reject             | montage reported stale, playback not interrupted                                                  |
  | Rebuild after that reject    | **2.6 s**, 7 parts re-rendered, 22 reused                                                         |
  | Play with track              | 15.3 s, montage 76.28 s, video and audio streams only                                             |
  | Boundaries against the beats | 9 of 28 cuts fall inside the 19.5 s the click fixture covers: mean 19 ms from a beat, worst 61 ms |
  | Errors                       | none                                                                                              |

  **The montage runs about one frame per clip longer than the edit asks for**, 77.24 s against 76.46 s. Each part is `-frames:v N` and N is the assigned duration rounded to a whole frame, so 29 clips accumulate 29 roundings. The index records the durations ffmpeg produced rather than the ones the edit asked for, so the timeline and the highlight are exact; what is off by a frame a clip is the montage against the export.

  **A reject re-renders more than the concat, and the design's expectation was too optimistic.** Seven of 28 parts came back, not zero: rejecting a clip re-runs the selection, and the selection reassigns durations, so seven clips' windows genuinely moved. The per part cache did its job on the 22 that did not.

  **The beat alignment cannot be judged by ear yet.** `~/Documents/autocut/tracks/` still does not exist, so the loop used the synthetic click again, and a 20 s click over a 76 s edit covers nine of the 28 cuts. Those nine sit a mean 19 ms from a beat, which is half a frame at 25 fps, and the worst is 61 ms; the residual is the same per part frame rounding. A real track is still the missing measurement.

- [x] 4.2 Update `SPEC.md` section 11 (screens 3 and 4). Run `make lint`, `make docker-test` and `make docker-test-gui`, commit on branch `feat/m5-montage-preview` following `sf-commit-convention`, open a pull request.

  Section 11 now describes Play all and Play with track, and carries a paragraph on how the montage is built, why it is parts and a concat rather than one filter graph, why the video's length wins over the track's, and that it runs a frame per clip long.

  **One more flake fixed while getting the gates green.** `make docker-test-gui` segfaulted after the last soundtrack test: a `QMediaPlayer` whose widget is garbage collected while it is still playing takes the process down, and in the container, where the audio backend is a stub, it does so reliably. The suite printed every test as passed and then died with exit 139, which is the same shape as the `QThread` flake from the previous change. An autouse fixture stops every player before teardown. Three consecutive container runs clean afterwards.

  Gates: `make lint` clean (ruff, format, mypy strict on 71 files). `make docker-test` **1089 passed, 61 skipped**. `make docker-test-gui` **262 passed**, three times. `make docker-test-ai` **8 passed, 13 skipped**. Both mypy passes hold: excluded on the Qt free image (47 files), full in `dev-gui` (71 files). In the venv, **1359 passed, 40 skipped**.

## 5. Review fixes on pull request 41

- [x] 5.1 Play with track follows `_synced_with_a_track()` rather than a loaded track, in both places that set it, so a sync that failed or was cancelled leaves the button off. The method refuses too and says why, because it is public and a montage of clips that are not on the grid is a preview of the wrong thing. A test patches `quantize_durations` to raise and asserts no segment carries beats, the button is off and the call returns False.

  **That test found a defect of its own**, in all three screens rather than only this one. A failed stage emits neither `stage_finished` nor `stage_cancelled`, so `_set_running(False)` never ran and the Review, Soundtrack and Export screens stayed disabled until the next stage did. All three now hook `state.error` as well, and the test asserts the screen comes back.

- [x] 5.2 The transport says the file name and the time, as the groups view does: `clip 3 of 29  DJI_0741.MP4  12.4 s`. `clip_labels(manifest)` builds the mapping and both screens hand it to the player, which has no manifest of its own; without labels the transport falls back to the id, which two tests pin down. Screenshots regenerated.

  Gates after these fixes: `make lint` clean. `make docker-test` **1089 passed, 61 skipped**. `make docker-test-gui` **267 passed**. Venv **1364 passed, 40 skipped**.
